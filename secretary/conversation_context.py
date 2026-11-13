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


def for_sources(value,source_ids):
    """Bind retained conditions to current evidence; older topics cannot set facts."""
    selected=set(source_ids)
    return [turn for turn in value if not turn['source_ids'] or selected.intersection(turn['source_ids'])]


def live_history(archive,value):
    """Do not send answers or conditions derived from removed sources again."""
    with archive.db() as db:
        ids={item for turn in value for item in turn['source_ids']}
        live={item for item in ids if db.execute("SELECT 1 FROM items WHERE id=? AND trashed_at=''",(item,)).fetchone()}
    return [turn for turn in value if set(turn['source_ids']).issubset(live)]
