"""Reconnectable question workers; final results live in the existing chat store."""
import copy
import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from . import ai
from .question_progress import QuestionProgress

FIELDS=('text','sources','catalog','timings','retrievalNotice','localReply','pending','error','retryable','requestId','requestState','questionId','requestApproval','requestVersion')

def preserve(incoming,previous):
    """Client snapshots must not roll back server-owned answers or active jobs."""
    known={message['id']:message for message in previous.get('messages',[])}
    result=copy.deepcopy(incoming)
    for message in result['messages']:
        old=known.get(message['id'])
        if old and old.get('requestId'):
            for key in FIELDS:
                if key in old:message[key]=copy.deepcopy(old[key])
                else:message.pop(key,None)
        elif not old or not old.get('requestId'):
            for key in ('requestId','requestState','requestApproval','requestVersion'):message.pop(key,None)
    present={m['id'] for m in result['messages']}
    for old in previous.get('messages',[]):
        if old.get('requestId') and old['id'] not in present:
            user=known.get(old.get('questionId'))
            if user and user['id'] not in present:result['messages'].append(copy.deepcopy(user));present.add(user['id'])
            result['messages'].append(copy.deepcopy(old));present.add(old['id'])
    return result

class QuestionJobs:
    def __init__(self,service):
        self.service=service;self.lock=threading.RLock();self.jobs={};self.closed=False
        self.pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='library-question')
        self.recover()

    def read(self):
        path=self.service.archive.root/'conversations.json'
        value=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'conversations':[],'activeId':''}
        if not isinstance(value,dict) or not isinstance(value.get('conversations'),list) or any(not isinstance(chat,dict) or not isinstance(chat.get('messages'),list) for chat in value['conversations']):raise ValueError('对话记录无法读取，请从备份恢复对话。')
        return value

    def patch(self,chat_id,message_id,request_id,values,starting=False,question_id=None,question=None):
        service=self.service;path=service.archive.root/'conversations.json'
        with service.lock:
            saved=self.read();data=copy.deepcopy(saved)
            chat=next((c for c in data['conversations'] if c['id']==chat_id),None)
            if chat is None:return None
            message=next((m for m in chat['messages'] if m['id']==message_id and m['role']=='assistant'),None)
            if message is None:return None
            if starting:
                user=next((m for m in chat['messages'] if m['id']==question_id and m['role']=='user'),None)
                if user is None or user.get('text')!=question:raise ValueError('问题与对话记录不一致，请刷新后重试')
                if message.get('requestState')=='running':raise ValueError('这条问答仍在进行，请先停止或等待完成')
                message['questionId']=question_id
                if not message.get('sources'):message.update(text='',sources=[],catalog=None,timings=None)
            elif message.get('requestId')!=request_id:return None
            message.update(copy.deepcopy(values),requestId=request_id)
            message.pop('questionProgress',None)
            chat['updated']=max(int(time.time()*1000),chat.get('updated',0)+1)
            message['requestVersion']=chat['updated']
            result=service.clean_chat_history(data,path,saved)
            # Permanent deletion may have removed the target while the model ran.
            live=next((c for c in result['conversations'] if c['id']==chat_id),{})
            return copy.deepcopy(next((m for m in live.get('messages',[]) if m['id']==message_id),None))

    def recover(self):
        try:
            with self.service.lock:data=self.read()
        except (OSError,ValueError,TypeError):return
        for chat in data['conversations']:
            for message in chat['messages']:
                if message.get('requestState')!='running':continue
                previous=bool(message.get('sources'))
                self.patch(chat['id'],message['id'],message['requestId'],{
                    'requestState':'interrupted','pending':False,'retryable':not previous,'error':not previous,
                    **({'retrievalNotice':'上次问答因程序重启而中断，已有答案已保留，可重新核对。'} if previous else {'text':'上次问答因程序重启而中断，可重试。'})})

    def start(self,body):
        key=body.get('progress_id');QuestionProgress.validate(key)
        chat_id,message_id,question_id=[body.get(field) for field in ('chat_id','message_id','question_id')]
        if any(not isinstance(value,str) or not 1<=len(value)<=100 for value in (chat_id,message_id,question_id)):raise ValueError('问答对话标识无效')
        question=body.get('question')
        if not isinstance(question,str) or not 0<len(question.strip())<=4000:raise ValueError('请输入有效问题')
        from .knowledge_chat import history
        from .conversation_context import turns
        history(body.get('history'));turns(body.get('context'))
        payload={key:body.get(key) for key in ('question','history','context','force_refresh')}
        fingerprint=hashlib.sha256(json.dumps([chat_id,message_id,question_id,payload],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        with self.lock:
            if self.closed:raise ValueError('程序正在退出，请稍后重试')
            if key in self.jobs:
                if self.jobs[key]['fingerprint']!=fingerprint:raise ValueError('问答标识已用于其他问题')
                return {'request_id':key}
            if sum(job['ended'] is None for job in self.jobs.values())>=8:raise ValueError('问答任务过多，请等待已有任务完成')
            # Only IDs/fingerprints remain in memory after completion, never a second answer copy.
            now=time.monotonic();self.jobs={k:v for k,v in self.jobs.items() if v['ended'] is None or now-v['ended']<3600}
            if len(self.jobs)>=128:raise ValueError('问答记录过多，请稍后重试')
            self.service.question_progress.begin(key)
            try:
                previous=self.patch(chat_id,message_id,key,{'pending':True,'error':False,'requestState':'running','retrievalNotice':'','requestApproval':None},True,question_id,question)
                if previous is None:raise ValueError('对话已删除，无法开始问答')
            except Exception:
                self.service.question_progress.update(key,'error');raise
            self.jobs[key]={'chat_id':chat_id,'message_id':message_id,'fingerprint':fingerprint,'ended':None}
            self.pool.submit(self.run,key,payload,previous)
        return {'request_id':key}

    def run(self,key,payload,previous):
        service=self.service
        with self.lock:job=dict(self.jobs[key])
        try:
            result=self.execute(key,payload,job)
            # Recheck existence, trash and company destination before restoring a saved result.
            ids=[source['item_id'] for source in result.get('sources',[])]
            for item in ids:service.archive.get(item)
            if ids and not result.get('catalog'):service.model_backend(item_ids=ids)
            self.patch(job['chat_id'],job['message_id'],key,{'text':result['answer'],'sources':result.get('sources',[]),
                'catalog':result.get('catalog'),'timings':result.get('timings'),'retrievalNotice':result.get('retrieval_notice',''),
                'localReply':result.get('local_reply',False),'pending':False,'error':False,'retryable':False,'requestState':'done','requestApproval':None})
            service.question_progress.update(key,'done')
        except Exception as error:
            cancelled=service.question_progress.event(key).is_set();state='cancelled' if cancelled else 'error'
            text='问答已停止，可重试。' if cancelled else str(error)[:1600]
            kept=bool(previous.get('sources'))
            values={'pending':False,'requestState':state,'retryable':not kept,'error':not kept and not cancelled}
            if kept:values['retrievalNotice']='重新核对未完成，保留上次回答。 '+text
            else:values.update(text=text,sources=[])
            try:self.patch(job['chat_id'],job['message_id'],key,values)
            finally:service.question_progress.update(key,state)
        finally:
            with self.lock:self.jobs[key]['ended']=time.monotonic()

    def execute(self,key,payload,job):
        from .company_ai import ApprovalRequired
        service=self.service;event=service.question_progress.event(key)
        for attempt in range(2):
            try:
                return service.ask_library(payload['question'],payload.get('history'),
                    lambda stage,count:service.question_progress.partial(key,count) if stage=='partial' else service.question_progress.update(key,stage,count),
                    context=payload.get('context'),force_refresh=payload.get('force_refresh') is True,cancel=event)
            except ApprovalRequired as error:
                if attempt:raise
                service.question_progress.update(key,'approval')
                self.patch(job['chat_id'],job['message_id'],key,{'requestApproval':error.info})
                deadline=time.monotonic()+180
                while not event.wait(.2):
                    status=service.company_model_status()
                    if status.get('fingerprint')!=error.info['fingerprint']:raise ValueError('模型配置已变化，请重新发起问答')
                    if status.get('approved'):break
                    if time.monotonic()>deadline:raise ValueError('模型确认已超时，可重新发起问答')
                if event.is_set():raise ai.ModelCancelledError('问答已停止。')
                self.patch(job['chat_id'],job['message_id'],key,{'requestApproval':None})

    def get(self,body):
        key=body.get('progress_id');QuestionProgress.validate(key)
        chat_id,message_id=body.get('chat_id'),body.get('message_id')
        # This is a local authenticated API, with target checks to prevent attaching
        # an unrelated request to a different conversation.
        with self.service.lock:
            data=self.read()
            chat=next((c for c in data['conversations'] if c['id']==chat_id),{})
            message=next((m for m in chat.get('messages',[]) if m['id']==message_id and m.get('requestId')==key),None)
            if message is None:raise ValueError('这条问答已删除或已被新的请求替代')
            value=copy.deepcopy(message)
        if value.get('requestApproval') and value.get('requestState')=='running':
            from .company_ai import ApprovalRequired
            if not self.service.company_model_status().get('approved'):raise ApprovalRequired(value['requestApproval'])
        progress=self.service.question_progress.snapshot(key)
        return {'message':value,'progress':progress}

    def active_count(self):
        with self.lock:return sum(job['ended'] is None for job in self.jobs.values())

    def close(self):
        with self.lock:
            self.closed=True;keys=[key for key,job in self.jobs.items() if job['ended'] is None]
        for key in keys:self.service.question_progress.cancel(key)
        self.pool.shutdown(wait=True)
