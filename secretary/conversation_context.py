"""Explicit user statements retained within a conversation, never source facts."""
from .knowledge_chat import history

CONDITION_PREFIX='【用户明确说明，作为条件而非资料事实】'

def turns(value):
    if value is None:return []
    if not isinstance(value,list) or len(value)>12:raise ValueError('对话依据格式无效')
    result=[]
    for entry in value:
        if not isinstance(entry,dict) or not isinstance(entry.get('statement'),str) or not 0<len(entry['statement'])<=1000:raise ValueError('对话依据格式无效')
        result.extend(history([{'question':CONDITION_PREFIX+entry['statement'],'answer':'','source_ids':entry.get('source_ids',[])}]))
    return result


def for_sources(value,source_ids):
    """Bind retained conditions to current evidence; older topics cannot set facts."""
    selected=set(source_ids)
    return [turn for turn in value if not turn['source_ids'] or selected.intersection(turn['source_ids'])]


def live_history(archive,value):
    """Do not send answers or conditions derived from removed sources again."""
    ids={item for turn in value for item in turn['source_ids']}
    if not ids:return value
    with archive.db() as db:
        slots=','.join('?' for _ in ids)
        live={row[0] for row in db.execute("SELECT id FROM items WHERE trashed_at='' AND id IN ("+slots+")",tuple(ids))}
    return [turn for turn in value if set(turn['source_ids']).issubset(live)]
