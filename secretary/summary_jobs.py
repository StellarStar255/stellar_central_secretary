"""Bounded model lanes and content-free timing records for this app session."""
import threading,time
from contextlib import contextmanager
from . import ai

class SummaryJobs:
    def __init__(self):
        self.lock=threading.RLock();self.jobs={};self.stopped=threading.Event()
        # One long call cannot consume the slot reserved for short/interactive work.
        self.lanes={'short':threading.Lock(),'long':threading.Lock()}
    def prune(self):
        finished=sorted((key for key,value in self.jobs.items() if value['ended'] is not None),key=lambda key:self.jobs[key]['ended'])
        for old in finished[:-100]:self.jobs.pop(old,None)
    def enqueue(self,key,chars=0,short=False):
        with self.lock:
            now=time.monotonic()
            self.jobs[key]={'stage':'queued','stage_at':now,'durations':{},'queued':now,'started':None,'ended':None,'input_chars':chars,'lane':'short' if short else 'long'}
            self.prune()
    def snapshot(self,key):
        with self.lock:
            value=self.jobs.get(key)
            if not value:return None
            now=value['ended'] or time.monotonic();start=value['started']
            durations=dict(value['durations'])
            if value['ended'] is None:durations[value['stage']]=durations.get(value['stage'],0)+now-value['stage_at']
            return {'stage':value['stage'],'active':value['ended'] is None,'lane':value['lane'],'input_chars':value['input_chars'],
                    'elapsed_seconds':round(now-value['queued'],1),'queue_seconds':round((start or now)-value['queued'],1),
                    'model_seconds':round(now-start,1) if start else 0,'stages_seconds':{stage:round(seconds,2) for stage,seconds in durations.items()}}
    def stage(self,key,stage):
        with self.lock:
            if key in self.jobs:
                value=self.jobs[key];now=time.monotonic();previous=value['stage']
                value['durations'][previous]=value['durations'].get(previous,0)+now-value['stage_at']
                value.update(stage=stage,stage_at=now)
    def finish(self,key,stage='done'):
        with self.lock:
            if key in self.jobs:self.stage(key,stage);self.jobs[key]['ended']=time.monotonic();self.prune()
    @contextmanager
    def session(self,key,chars=0,short=False):
        with self.lock:
            if key not in self.jobs or self.jobs[key]['ended'] is not None:self.enqueue(key,chars,short)
            lane=self.lanes[self.jobs[key]['lane']]
        acquired=False;failed=True
        try:
            while not self.stopped.is_set():
                if lane.acquire(timeout=.1):acquired=True;break
            if self.stopped.is_set():raise RuntimeError('任务已停止，已有资料保持不变。')
            with self.lock:self.jobs[key].update(started=time.monotonic());self.stage(key,'preparing')
            with ai.progress(lambda stage:self.stage(key,stage)):yield
            failed=False
        finally:
            self.finish(key,'stopped' if self.stopped.is_set() else 'error' if failed else 'done')
            if acquired:lane.release()
    def close(self):self.stopped.set()
