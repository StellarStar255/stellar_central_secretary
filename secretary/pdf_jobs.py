"""Bounded, cancellable local PDF extraction jobs; no model calls."""
import threading,uuid
from concurrent.futures import ThreadPoolExecutor
from . import pdf_reading

class PdfJobs:
    def __init__(self,service):
        self.service=service;self.lock=threading.RLock();self.pool=ThreadPoolExecutor(max_workers=1);self.jobs={}
    def start(self,item_id,batch_id,key,body):
        start,end=body.get('start',1),body.get('end',5)
        if type(start) is not int or type(end) is not int or start<1 or end<start or end-start>=10:raise ValueError('每次请选择连续 1–10 页')
        pdf_reading.owned(self.service.archive,item_id,batch_id,key)
        with self.service.lock,self.lock:
            if item_id in self.service.busy or item_id in self.service.captures:raise ValueError('资料正在处理，请稍后读取')
            for ident in list(self.jobs):
                if len(self.jobs)<24:break
                if self.jobs[ident]['state'] in ('done','error','cancelled'):del self.jobs[ident]
            if len(self.jobs)>=24:raise ValueError('页面读取任务过多，请稍后重试')
            ident=uuid.uuid4().hex;job={'id':ident,'item_id':item_id,'state':'queued','completed':0,'total':end-start+1,'page':start,'cancel':threading.Event()};self.jobs[ident]=job;self.service.busy.add(item_id)
            self.pool.submit(self.run,job,batch_id,key,dict(body));return self.public(job)
    def public(self,job):return {key:value for key,value in job.items() if key!='cancel'}
    def get(self,ident):
        with self.lock:
            job=self.jobs.get(ident)
            if not job:raise KeyError('页面读取任务不存在')
            self.service.archive.get(job['item_id']);return self.public(job)
    def cancel(self,ident):
        with self.lock:
            job=self.jobs.get(ident)
            if not job:raise KeyError('页面读取任务不存在')
            if job['state'] in ('queued','reading'):
                job['cancel'].set();job['state']='stopping'
            return self.public(job)
    def run(self,job,batch_id,key,body):
        def stopped():return job['cancel'].is_set() or self.service.stopping
        def progress(completed,total,page):
            with self.lock:job.update(completed=completed,total=total,page=page)
        try:
            with self.lock:
                if not stopped():job['state']='reading'
            result=pdf_reading.read(self.service.archive,job['item_id'],batch_id,key,body,stopped,progress)
            with self.lock:job.update(state='done',result=result)
        except Exception as error:
            with self.lock:job.update(state='cancelled' if stopped() else 'error',error=str(error)[:1000])
        finally:
            with self.service.lock:self.service.busy.discard(job['item_id'])
    def close(self):
        with self.lock:
            for job in self.jobs.values():job['cancel'].set()
        self.pool.shutdown(wait=False,cancel_futures=False)
