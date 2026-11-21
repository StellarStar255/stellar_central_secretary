"""Paired mobile access to the existing desktop conversation and question store."""
import base64,binascii,copy,hashlib,json,re,time,uuid
from . import bundles, knowledge_chat

class ChatBusy(ValueError):pass

CONDITION=re.compile(r'(?:这(?:张|份|个).*(?:就是|属于|为准|判断)|(?:按|依据|利用|用)这.*(?:判断|为准|即可|就行)|对象是|不是.{1,30}而是|以后(?:都|请)|每(?:天|周).*(?:按|用|执行)|改为|更正为|确认.{1,30}(?:是|属于))',re.I)

def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def attachment_batch(values):
    if not isinstance(values,list) or not 1<=len(values)<=8:
        raise ValueError('每次可添加 1 至 8 个附件。')
    files=[];identities=[];size=0
    for attachment in values:
        if not isinstance(attachment,dict):raise ValueError('附件格式无效')
        name,data=attachment.get('name'),attachment.get('data')
        if not isinstance(name,str) or not 1<=len(name.strip())<=300 or '/' in name or '\\' in name or not isinstance(data,str) or len(data)>14*1024**2:
            raise ValueError('附件名称无效或超过 10 MB。')
        try:raw=base64.b64decode(data,validate=True)
        except (ValueError,binascii.Error):raise ValueError('附件编码无效') from None
        size+=len(raw)
        if not raw or size>10*1024**2:raise ValueError('附件须为非空文件，合计最多 10 MB。')
        files.append({'name':name,'data':data})
        identities.append([name,hashlib.sha256(raw).hexdigest()])
    return files,identities
def identifier(value):
    if not isinstance(value,str) or not 1<=len(value)<=100:raise ValueError('会话标识无效')
    return value

def sources(message):
    values=message.get('sources') or []
    numbers={int(a or b) for a,b in re.findall(r'\[(\d{1,3})\]|【(\d{1,3})】',message.get('text',''))}
    return [source for source in values if isinstance(source,dict) and (not numbers or source.get('number') in numbers)]

def context(chat,end=None):
    """Match desktop knowledgeHistory/rememberedContext, including edited conditions."""
    messages=chat.get('messages',[]);end=len(messages) if end is None else end
    ignored=set(chat.get('contextIgnored',[]));edits=chat.get('contextEdits',{})
    reset=next((i for i,m in enumerate(messages) if m['id']==chat.get('contextReset')),-1)
    turns=[];claims=[];cited=[]
    for index,message in enumerate(messages[:end]):
        text=message.get('text','');condition=bool(CONDITION.search(text))
        refs=list(dict.fromkeys(s.get('item_id') for s in sources(message) if s.get('item_id')))
        if index>reset and message.get('role')=='assistant' and refs:cited=refs[:3]
        if index>reset and message.get('role')=='user' and message['id'] not in ignored and message.get('knowledgeQuestion') and len(text)<=1000 and condition:
            claims.append({'statement':edits.get(message['id'],text),'source_ids':list(cited)})
        answer=messages[index+1] if index+1<end else None
        if condition and (message['id'] in ignored or index<=reset):continue
        if message.get('role')=='user' and answer and answer.get('role')=='assistant' and (message.get('knowledgeQuestion') or not answer.get('archiveOnly') and answer.get('sources')) and not any(answer.get(key) for key in ('pending','error','localReply')) and not knowledge_chat.social_reply(text):
            turns.append({'question':edits.get(message['id'],text)[:2000],'answer':answer.get('text','')[:4000],'source_ids':list(dict.fromkeys(s['item_id'] for s in sources(answer) if s.get('item_id')))[:12]})
    recent=turns[-6:]
    if not any(turn['source_ids'] for turn in recent):
        anchor=next((turn for turn in reversed(turns) if turn['source_ids']),None)
        if anchor:recent=[anchor]+recent[-5:]
    return recent,claims[-12:]

class SharedChat:
    def __init__(self,service):self.service=service
    def read(self):return self.service.chat_history()
    def listing(self,revision=''):
        data=self.read()
        chats=[{'id':c['id'],'title':c['title'],'updated':c.get('updated',0),'running':any(m.get('pending') or m.get('requestState')=='running' for m in c['messages'])} for c in data['conversations']]
        value={'conversations':chats,'active_id':data.get('activeId','')};version=digest(value)
        return {'revision':version,**({'unchanged':True} if revision==version else value)}
    def create(self,device,body):
        request=identifier(body.get('request_id'));key=digest(['chat',device,request])[:32]
        service=self.service
        with service.lock:
            saved=service.question_jobs.read();data=copy.deepcopy(saved)
            if body.get('reuse_active') is True and data['conversations']:
                active=data.get('activeId')
                chat=next((chat for chat in data['conversations'] if chat['id']==active),data['conversations'][0])
                return {'chat_id':chat['id']}
            if not any(c['id']==key for c in data['conversations']):
                data['conversations'].insert(0,{'id':key,'title':'新对话','messages':[],'updated':int(time.time()*1000),'dialogueActive':True,'inputMode':'library'})
                data['activeId']=key
                service.clean_chat_history(data,service.archive.root/'conversations.json',saved)
        return {'chat_id':key}
    def public_message(self,message):
        result={key:message[key] for key in ('id','role','text','pending','error','requestState','requestId','mobileRequestId','questionId','retryable','archiveOnly','files') if key in message}
        result['sources']=[{key:source[key] for key in ('item_id','title','number') if key in source} for source in sources(message)]
        for item_id in message.get('items',[])[:20]:
            if any(s.get('item_id')==item_id for s in result['sources']):continue
            try:item=self.service.archive.get(item_id)
            except (ValueError,KeyError):continue
            result['sources'].append({'item_id':item_id,'title':item['title']})
        return result
    def detail(self,chat_id,revision='',before='',partial_offset=0,partial_id=''):
        data=self.read();chat=next((c for c in data['conversations'] if c['id']==chat_id),None)
        if not chat:raise ValueError('会话不存在或已删除，请刷新会话列表')
        version=digest(chat);messages=chat['messages'];end=len(messages)
        if before:
            index=next((i for i,m in enumerate(messages) if m['id']==before),None)
            if index is None:raise ValueError('会话已变化，请重新加载')
            end=index
        start=max(0,end-20)
        result={'chat_id':chat_id,'revision':version,'title':chat['title']}
        if revision==version and not before:result['unchanged']=True
        else:result.update(messages=[self.public_message(m) for m in messages[start:end]],has_more=start>0,deleted_ids=[mid for cid,mid in data.get('deletedMessages',[]) if cid==chat_id])
        running=next((m for m in reversed(messages) if m.get('requestId') and m.get('requestState')=='running'),None)
        if running:
            state=self.service.question_progress.snapshot(running['requestId']);partial=state.get('partial','')
            offset=int(partial_offset) if partial_id==running['id'] else 0
            if not 0<=offset<=16000:raise ValueError('回答进度无效')
            result['progress']={'message_id':running['id'],'stage':state['stage'],'partial':partial[offset:] if offset<=len(partial) else partial,'offset':len(partial),'reset':partial_id!=running['id'] or offset>len(partial)}
        return result
    def send(self,device,chat_id,body):
        request=identifier(body.get('request_id'));text=body.get('text')
        attachment=body.get('attachment');batch=body.get('attachments')
        if attachment is not None and batch is not None:raise ValueError('附件格式无效')
        if not isinstance(text,str) or len(text.strip())>4000 or not (text.strip() or attachment or batch):raise ValueError('请输入消息或添加附件，文字最多 4000 字。')
        files=[];file_digest=''
        if attachment is not None or batch is not None:
            files,identities=attachment_batch(batch if batch is not None else [attachment])
            file_digest=digest(identities[0] if len(files)==1 else identities)
        question=text if text.strip() else ('请整理这些附件的主要内容。' if len(files)>1 else '请整理这份附件的主要内容。')
        key=digest(['message',device,request])[:32];question_id='phone-user-'+key;message_id='phone-answer-'+key
        service=self.service;jobs=service.question_jobs
        # Same ordering as QuestionJobs.start: job lock, then store lock.
        with jobs.lock:
            with service.lock:
                if service.stopping:raise ValueError('电脑正在退出，请稍后重试')
                saved=jobs.read();data=copy.deepcopy(saved);chat=next((c for c in data['conversations'] if c['id']==chat_id),None)
                if not chat:raise ValueError('会话不存在或已删除，请刷新会话列表')
                previous=next((m for c in data['conversations'] for m in c['messages'] if m['id']==question_id),None)
                if previous:
                    if previous.get('text')!=question or previous.get('mobileAttachmentDigest','')!=file_digest or not any(m['id']==question_id for m in chat['messages']):raise ValueError('消息标识已用于其他内容')
                    return {'accepted':True,'chat_id':chat_id,'message_id':message_id}
                refs=service.archive.deletion_refs()
                if [chat_id,question_id] in refs['deletedMessages'] or [chat_id,message_id] in refs['deletedMessages']:raise ValueError('这条消息已被删除，请勿重复发送')
                if any(m.get('pending') or m.get('requestState')=='running' for m in chat['messages']):raise ChatBusy('这段对话仍在回答，请等待完成后发送')
                history,retained=context(chat)
                material_id=''
                if files:
                    title=text.strip().split('\n',1)[0][:100] or files[0]['name']
                    data_file,source=bundles.create(text,files)
                    try:material_id,created=service.archive.add(title,source,filename='materials.stellar.zip',data=data_file)
                    finally:bundles.cleanup(data_file)
                    if created:service.archive.update(material_id,state='saved')
                if not chat['messages'] and not chat.get('titleCustom'):chat['title']=(text.strip() or (files[0]['name'] if files else question))[:36]
                chat.update(updated=max(int(time.time()*1000),chat.get('updated',0)+1),dialogueActive=True,inputMode='library')
                user={'id':question_id,'role':'user','text':question,'knowledgeQuestion':True,'mobileRequestId':request}
                if files:user.update(files=[file['name'] for file in files],items=[material_id],mobileMaterial=material_id,mobileAttachmentDigest=file_digest)
                chat['messages'] += [user,
                    {'id':message_id,'role':'assistant','text':'','pending':True,'requestState':'queued','requestId':key,'questionId':question_id}]
                service.clean_chat_history(data,service.archive.root/'conversations.json',saved)
            try:
                jobs.start({'progress_id':key,'chat_id':chat_id,'message_id':message_id,'question_id':question_id,'question':question,'history':history,'context':retained})
            except Exception as error:
                jobs.patch(chat_id,message_id,key,{'text':str(error)[:1600],'pending':False,'requestState':'error','error':True,'retryable':True})
        return {'accepted':True,'chat_id':chat_id,'message_id':message_id}
    def stop(self,chat_id,body):
        with self.service.lock:
            data=self.service.question_jobs.read();chat=next((c for c in data['conversations'] if c['id']==chat_id),None)
            message=next((m for m in (chat or {}).get('messages',[]) if m['id']==body.get('message_id')),None)
            if not message or message.get('requestState')!='running' or not message.get('requestId'):raise ValueError('回答已结束或不存在，请刷新对话')
            key=message['requestId']
        return {'cancelled':self.service.question_progress.cancel(key)}
