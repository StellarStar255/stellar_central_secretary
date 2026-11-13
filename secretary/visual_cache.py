"""Bounded prepared-image reuse; every answer still receives the actual image."""
import copy
import json
import threading
import time
from collections import OrderedDict
from .answer_cache import files

class VisualCache:
    def __init__(self):
        self.lock=threading.Lock();self.entries=OrderedDict()

    def signature(self,archive,passages,backend):
        ids=sorted({p['item_id'] for p in passages})
        signature=files(archive,ids)
        if signature is None:return None
        with archive.db() as db:
            revisions=[tuple(db.execute('SELECT id,updated,trashed_at FROM items WHERE id=?',(item,)).fetchone() or ()) for item in ids]
        return json.dumps([[(p['item_id'],p.get('origin',{})) for p in passages],revisions,signature,
                           not isinstance(backend,dict) or backend.get('vision',False)],sort_keys=True)

    def prepare(self,archive,passages,backend,build,force=False):
        key=self.signature(archive,passages,backend)
        with self.lock:
            entry=self.entries.get(key) if key is not None and not force else None
            if entry and time.monotonic()-entry[0]<300:
                self.entries.move_to_end(key);return (*copy.deepcopy(entry[1]),True)
        result=build()
        if key is not None and key==self.signature(archive,passages,backend):
            size=sum(len(image['data']) for image in result[0])
            with self.lock:
                self.entries[key]=(time.monotonic(),copy.deepcopy(result),size)
                self.entries.move_to_end(key)
                while len(self.entries)>8 or sum(v[2] for v in self.entries.values())>24*1024*1024:self.entries.popitem(last=False)
        return (*result,False)
