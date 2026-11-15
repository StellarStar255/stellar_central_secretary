"""Persist a browser capture receipt in the chat active when capture was submitted."""
import copy
import json
import re
import time
from datetime import datetime, timezone


def ingest(service, body):
    event = body.get('extension_event_id', '')
    if not isinstance(event, str) or not re.fullmatch('[a-f0-9]{32}', event):
        raise ValueError('浏览器采集请求标识无效，请重新加载扩展。')
    target = service.chat_history().get('activeId', '')
    with service.archive.db() as db:
        previous = db.execute("SELECT text FROM items WHERE url=? AND trashed_at='' LIMIT 1", (body.get('url', ''),)).fetchone()
    result = service.ingest(body)
    if previous and previous['text'].strip() == str(body.get('text', '')).strip() and not result['created']:
        result['updated'] = False
    item = result['item']
    bookmark = body.get('archive_only') is True and bool(body.get('url')) and not body.get('text')
    if not bookmark and item.get('text', '').strip() != str(body.get('text', '')).strip():
        return result
    text = ('链接已收藏，未采集正文或绘图。' if result['created'] else '这个链接已存在，可直接查看。') if bookmark else '浏览器采集已归档。' if result['created'] else '浏览器采集已补充正文。' if result['updated'] else '这份资料已存在，可直接查看。'
    return append_receipt(service,result,target,event,text)

def append_receipt(service,result,target,event,text,namespace='extension'):
    item=result['item']
    try:
        with service.lock:
            path = service.archive.root / 'conversations.json'
            saved = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'conversations': [], 'activeId': ''}
            data = copy.deepcopy(saved)
            message_id = namespace + '-' + event
            # A retry must not create a second receipt, even if the active chat changed.
            if any(m['id'] == message_id for c in data['conversations'] for m in c['messages']):
                result['chat_synced'] = True
                return result
            chat = next((c for c in data['conversations'] if c['id'] == target), None)
            if target and chat is None:
                result['chat_sync_error'] = '原对话已移除，资料已保存在知识库。'
                return result
            if chat is None:
                chat = {'id': namespace + '-chat-' + event, 'title': item['title'][:36], 'messages': []}
                data['conversations'].append(chat)
                if not data.get('activeId'): data['activeId'] = chat['id']
            chat['messages'].append({'id': message_id, 'role': 'assistant', 'text': text,
                                     'items': [item['id']], 'externalArchive': True,
                                     'createdAt': datetime.now(timezone.utc).isoformat()})
            chat['updated'] = max(int(time.time() * 1000), chat.get('updated', 0) + 1)
            service.clean_chat_history(data, service.archive.root / 'conversations.json', saved)
            result['chat_synced'] = True
    except Exception:
        # Saving the receipt must not turn a successful archive into a failed ingest.
        result['chat_sync_error'] = '资料已保存，但归档卡片未同步到聊天，请在知识库查看。'
    return result
