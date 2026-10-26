"""Remove messages tied to deleted archives without retaining their content."""
import copy


def clean_chats(chats,deleted_items,deleted_messages):
    deleted_items=set(deleted_items);removed=set(deleted_messages);result=[]
    affected={chat for chat,_ in removed}
    for original in chats:
        chat=copy.deepcopy(original);messages=chat.get('messages',[]);drop=set()
        for index,message in enumerate(messages):
            items=message.get('items',[]);sources=message.get('sources',[])
            refs=[key for key in items if isinstance(key,str)] if isinstance(items,list) else []
            if isinstance(sources,list):refs.extend(source.get('item_id') for source in sources if isinstance(source,dict) and isinstance(source.get('item_id'),str))
            if isinstance(message.get('images'),list):refs.extend(image.get('item_id') for image in message['images'] if isinstance(image,dict) and isinstance(image.get('item_id'),str))
            if (chat['id'],message['id']) in removed or deleted_items.intersection(refs):
                drop.add(index)
                if message.get('role')=='assistant' and index and messages[index-1].get('role')=='user':drop.add(index-1)
        if drop:
            affected.add(chat['id'])
            removed.update((chat['id'],messages[index]['id']) for index in drop)
            chat['messages']=[message for index,message in enumerate(messages) if index not in drop]
        if chat['id'] in affected:
            if not chat['messages']:continue
            user=next((message for message in chat['messages'] if message.get('role')=='user'),{})
            files=user.get('files',[])
            chat['title']=(user.get('text') or (files[0] if isinstance(files,list) and files else '') or 'Conversation')[:36]
        result.append(chat)
    return result,removed
