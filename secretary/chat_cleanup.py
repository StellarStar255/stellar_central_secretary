"""Remove messages tied to deleted archives without retaining their content."""
import copy


def validate_chat_history(history):
    if not isinstance(history, dict):
        raise ValueError('对话记录格式无效')
    chats = history.get('conversations')
    if not isinstance(chats, list) or len(chats) > 500 or not isinstance(history.get('activeId', ''), str):
        raise ValueError('对话记录格式无效')
    for chat in chats:
        if (not isinstance(chat, dict) or not isinstance(chat.get('id'), str)
                or not isinstance(chat.get('title'), str) or not isinstance(chat.get('messages'), list)):
            raise ValueError('对话记录格式无效')
        updated = chat.get('updated', 0)
        if not isinstance(updated, (int, float)) or not 0 <= updated <= 10**15:
            raise ValueError('对话时间格式无效')
        for message in chat['messages']:
            if (not isinstance(message, dict) or message.get('role') not in ('user', 'assistant')
                    or not isinstance(message.get('id'), str) or not isinstance(message.get('text', ''), str)):
                raise ValueError('消息格式无效')


def clean_chats(chats,deleted_items,deleted_messages):
    deleted_items=set(deleted_items);removed=set(deleted_messages);result=[]
    affected={chat for chat,_ in removed}
    for original in chats:
        chat=copy.deepcopy(original);messages=chat.get('messages',[]);drop=set()
        for index,message in enumerate(messages):
            evidence=message.get('answerEvidence')
            if isinstance(evidence,dict) and isinstance(evidence.get('pdf_pages'),list):
                evidence['pdf_pages']=[page for page in evidence['pdf_pages'] if isinstance(page,dict) and page.get('item_id') not in deleted_items]
            items=message.get('items',[]);sources=message.get('sources',[])
            refs=[key for key in items if isinstance(key,str)] if isinstance(items,list) else []
            if isinstance(sources,list):refs.extend(source.get('item_id') for source in sources if isinstance(source,dict) and isinstance(source.get('item_id'),str))
            if isinstance(message.get('images'),list):refs.extend(image.get('item_id') for image in message['images'] if isinstance(image,dict) and isinstance(image.get('item_id'),str))
            if (chat['id'],message['id']) in removed or deleted_items.intersection(refs):
                drop.add(index)
                if message.get('role')=='assistant' and not message.get('externalArchive') and index and messages[index-1].get('role')=='user':drop.add(index-1)
        if drop:
            affected.add(chat['id'])
            removed.update((chat['id'],messages[index]['id']) for index in drop)
            chat['messages']=[message for index,message in enumerate(messages) if index not in drop]
            kept={message['id'] for message in chat['messages']}
            if isinstance(chat.get('contextEdits'),dict):chat['contextEdits']={key:value for key,value in chat['contextEdits'].items() if key in kept}
            if isinstance(chat.get('contextIgnored'),list):chat['contextIgnored']=[key for key in chat['contextIgnored'] if key in kept]
            if chat.get('contextReset') and chat['contextReset'] not in kept:
                boundary=next((i for i,m in enumerate(messages) if m['id']==chat['contextReset']),-1)
                chat['contextReset']=next((m['id'] for m in reversed(messages[:boundary+1]) if m['id'] in kept),'')
        if chat['id'] in affected:
            if not chat['messages']:continue
            user=next((message for message in chat['messages'] if message.get('role')=='user'),{})
            files=user.get('files',[])
            if not chat.get('titleCustom'):chat['title']=(user.get('text') or (files[0] if isinstance(files,list) and files else '') or 'Conversation')[:36]
        result.append(chat)
    return result,removed
