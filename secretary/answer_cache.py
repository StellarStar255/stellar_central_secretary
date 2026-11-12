"""Small in-memory answer cache; source, context, time and backend changes invalidate it."""
import copy
import hashlib
import json
import itertools
import re
import threading
import time
from collections import OrderedDict
from pathlib import Path
from .knowledge_chat import current_time
from . import __version__

def key(archive,question,turns,backend,generation=0):
    context=list(turns)
    while context and context[-1]['question']==question:context.pop()
    with archive.db() as db:
        revision=[tuple(row) for row in db.execute('SELECT id,updated,trashed_at FROM items ORDER BY id')]
        semantic_settings=db.execute("SELECT value FROM settings WHERE key='semantic_search'").fetchone()
        semantic_state=[semantic_settings[0] if semantic_settings else '',db.execute('SELECT count(*) FROM semantic_vectors').fetchone()[0],generation]
    config=backend if isinstance(backend,dict) else {'name':str(backend),'proxy':getattr(backend,'proxy',None)}
    now=current_time()
    payload=[__version__,question,context,config,revision,semantic_state,now['date'],now['time'],now['utc_offset']]
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def files(archive,ids):
    result=[]
    originals=set(ids)
    with archive.db() as db:
        for item in ids:
            row=db.execute('SELECT additions FROM items WHERE id=?',(item,)).fetchone()
            if row:
                for batch in json.loads(row[0]):
                    if isinstance(batch,dict) and isinstance(batch.get('id'),str) and re.fullmatch('[a-f0-9]{32}',batch['id']):originals.add(batch['id'])
    for item in sorted(originals):
        root=archive.root/'files'/item
        if root.is_symlink():return None
        paths=[root] if root.is_file() else list(itertools.islice(root.rglob('*'),2001)) if root.is_dir() else []
        if len(paths)>2000:return None
        for path in sorted(paths):
            try:info=path.lstat()
            except OSError:return None
            result.append((str(path.relative_to(archive.root)),info.st_size,info.st_mtime_ns,info.st_ctime_ns))
    return result

class AnswerCache:
    def __init__(self):self.lock=threading.Lock();self.entries=OrderedDict()
    def get(self,key,archive):
        with self.lock:
            entry=self.entries.get(key)
            if not entry:return None
            if time.monotonic()-entry['at']>300 or files(archive,entry['ids'])!=entry['files']:
                self.entries.pop(key,None);return None
            self.entries.move_to_end(key);return copy.deepcopy(entry['response'])
    def put(self,key,archive,response,passages,signature=None):
        if not response.get('sources'):return
        ids=[p['item_id'] for p in passages]
        if signature is None:signature=files(archive,ids)
        if signature is None:return
        with self.lock:
            self.entries[key]={'at':time.monotonic(),'response':copy.deepcopy(response),'ids':ids,'files':signature}
            self.entries.move_to_end(key)
            while len(self.entries)>32:self.entries.popitem(last=False)
