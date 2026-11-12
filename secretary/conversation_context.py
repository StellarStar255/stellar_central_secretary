"""Explicit user statements retained within a conversation, never source facts."""
from .knowledge_chat import history

def turns(value):
    if value is None:return []
    if not isinstance(value,list) or len(value)>12:raise ValueError('对话依据格式无效')
    result=[]
    for entry in value:
        if not isinstance(entry,dict) or not isinstance(entry.get('statement'),str) or not 0<len(entry['statement'])<=1000:raise ValueError('对话依据格式无效')
        result.extend(history([{'question':'【用户明确说明，作为条件而非资料事实】'+entry['statement'],'answer':'','source_ids':entry.get('source_ids',[])}]))
    return result
