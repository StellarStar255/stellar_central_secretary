"""Optional loopback-only Ollama embeddings and an incremental SQLite vector cache."""
import array
import hashlib
import heapq
import ipaddress
import json
import math
import re
import sys
import threading
import urllib.error
import urllib.request
from urllib.parse import urlsplit

DEFAULT={'enabled':False,'base_url':'http://127.0.0.1:11434','model':'bge-m3','min_score':0.45}
KEY='semantic_search'


def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS semantic_vectors(
        chunk_id INTEGER PRIMARY KEY, signature TEXT NOT NULL, digest TEXT NOT NULL,
        dimensions INTEGER NOT NULL, vector BLOB NOT NULL);
        CREATE TRIGGER IF NOT EXISTS semantic_chunk_deleted AFTER DELETE ON chunks BEGIN
            DELETE FROM semantic_vectors WHERE chunk_id=OLD.id;
        END;
        CREATE TRIGGER IF NOT EXISTS semantic_chunk_changed AFTER UPDATE ON chunks BEGIN
            DELETE FROM semantic_vectors WHERE chunk_id=OLD.id;
        END;
        CREATE TRIGGER IF NOT EXISTS semantic_title_changed AFTER UPDATE OF title ON items BEGIN
            DELETE FROM semantic_vectors WHERE chunk_id IN (SELECT id FROM chunks WHERE item_id=NEW.id);
        END;''')


def normalize(body):
    if not isinstance(body,dict):raise ValueError('语义检索设置格式无效')
    value={key:body.get(key,default) for key,default in DEFAULT.items()}
    if type(value['enabled']) is not bool:raise ValueError('语义检索设置格式无效')
    url=value['base_url']
    if not isinstance(url,str) or len(url)>200:raise ValueError('语义服务地址仅支持本机回环地址')
    try:
        parsed=urlsplit(url.strip())
        host=parsed.hostname
        # Use numeric loopback addresses, so a DNS name cannot route library text elsewhere.
        if host=='localhost':host='127.0.0.1'
        if parsed.scheme not in ('http','https') or not ipaddress.ip_address(host).is_loopback or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
            raise ValueError()
        port=parsed.port
        if port is not None and port<1:raise ValueError()
        authority=('['+host+']' if ':' in host else host)+((':'+str(port)) if port else '')
    except (ValueError,TypeError):raise ValueError('语义服务地址仅支持本机回环地址') from None
    value['base_url']=parsed.scheme+'://'+authority
    if not isinstance(value['model'],str) or not re.fullmatch(r'[a-zA-Z0-9_.:/-]{1,150}',value['model']):raise ValueError('请填写本机嵌入模型名称')
    if type(value['min_score']) not in (int,float) or not math.isfinite(value['min_score']) or not 0<=value['min_score']<=1:raise ValueError('语义相似度阈值需在 0 到 1 之间')
    return value


def config(archive):
    with archive.db() as db:row=db.execute('SELECT value FROM settings WHERE key=?',(KEY,)).fetchone()
    try:return normalize(json.loads(row[0])) if row else dict(DEFAULT)
    except (ValueError,TypeError):return dict(DEFAULT)


def signature(value):
    return hashlib.sha256((value['base_url']+'\n'+value['model']+'\nfloat32-v1').encode()).hexdigest()


def text(row):return row['title']+'\n'+row['text']
def digest(row):return hashlib.sha256(text(row).encode()).hexdigest()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def unit(vector):
    if not isinstance(vector,list) or not 1<=len(vector)<=8192 or any(type(v) not in (int,float) or not math.isfinite(v) for v in vector):raise ValueError('嵌入模型返回了无效向量')
    norm=math.hypot(*vector)
    if not math.isfinite(norm) or norm==0:raise ValueError('嵌入模型返回了无效向量')
    return [v/norm for v in vector]


def embed(value,inputs,timeout=15):
    value=normalize(value)
    payload=json.dumps({'model':value['model'],'input':inputs,'truncate':False},ensure_ascii=False).encode()
    request=urllib.request.Request(value['base_url']+'/api/embed',data=payload,headers={'Content-Type':'application/json'})
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    try:
        with opener.open(request,timeout=timeout) as response:raw=response.read(8_000_001)
        if len(raw)>8_000_000:raise ValueError('嵌入模型返回内容过大')
        result=json.loads(raw);vectors=result.get('embeddings')
        if not isinstance(vectors,list) or len(vectors)!=len(inputs):raise ValueError('嵌入模型返回的向量数量不正确')
        vectors=[unit(vector) for vector in vectors]
        if len({len(v) for v in vectors})!=1:raise ValueError('嵌入模型返回的向量维度不一致')
        return vectors
    except urllib.error.HTTPError as exc:
        raise RuntimeError('本机嵌入服务请求失败，请确认模型已下载且支持嵌入（HTTP '+str(exc.code)+'）') from None
    except (urllib.error.URLError,OSError,TimeoutError):
        raise RuntimeError('无法连接本机嵌入服务，请启动 Ollama 并检查地址') from None
    except (KeyError,TypeError,AttributeError,json.JSONDecodeError):
        raise ValueError('嵌入模型返回了无效向量') from None


class SemanticIndex:
    def __init__(self,archive):
        self.archive=archive;self.stop=threading.Event();self.wake=threading.Event()
        self.lock=threading.RLock();self.thread=None;self.error='';self.building=False;self.generation=0
        self.start()

    def start(self):
        with self.lock:
            if config(self.archive)['enabled'] and self.thread is None and not self.stop.is_set():
                self.thread=threading.Thread(target=self._worker,name='semantic-index',daemon=True);self.thread.start()
        self.wake.set()

    def close(self):
        self.stop.set();self.wake.set()
        if self.thread:self.thread.join(timeout=1)

    def save(self,body,rebuild=False):
        value=normalize(body)
        with self.archive.lock,self.lock,self.archive.db() as db:
            previous=config(self.archive)
            if rebuild or signature(previous)!=signature(value):db.execute('DELETE FROM semantic_vectors')
            db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(KEY,json.dumps(value)))
            self.error='';self.generation+=1
        self.start()
        return self.status()

    def status(self):
        value=config(self.archive);sig=signature(value)
        with self.archive.db() as db:
            total=db.execute("SELECT count(*) FROM chunks c JOIN items i ON i.id=c.item_id WHERE i.trashed_at=''").fetchone()[0]
            indexed=db.execute("SELECT count(*) FROM semantic_vectors v JOIN chunks c ON c.id=v.chunk_id JOIN items i ON i.id=c.item_id WHERE v.signature=? AND i.trashed_at=''",(sig,)).fetchone()[0]
        with self.lock:return dict(config=value,total=total,indexed=indexed,building=self.building,error=self.error)

    def build_batch(self):
        value=config(self.archive)
        if not value['enabled'] or self.stop.is_set():return 0
        with self.lock:generation=self.generation
        sig=signature(value)
        with self.archive.db() as db:
            rows=[dict(row) for row in db.execute("""SELECT c.*,i.title FROM chunks c JOIN items i ON i.id=c.item_id
                LEFT JOIN semantic_vectors v ON v.chunk_id=c.id AND v.signature=?
                WHERE i.trashed_at='' AND v.chunk_id IS NULL ORDER BY c.id LIMIT 16""",(sig,))]
        if not rows:return 0
        vectors=embed(value,[text(row) for row in rows],timeout=30)
        if self.stop.is_set():return 0
        written=0
        with self.archive.lock,self.lock,self.archive.db() as db:
            current=config(self.archive)
            if not current['enabled'] or signature(current)!=sig or generation!=self.generation:return 0
            previous=db.execute('SELECT dimensions FROM semantic_vectors WHERE signature=? LIMIT 1',(sig,)).fetchone()
            if previous and previous[0]!=len(vectors[0]):raise ValueError('嵌入模型维度已变化，请重建语义索引')
            for row,vector in zip(rows,vectors):
                latest=db.execute("SELECT c.*,i.title,i.trashed_at FROM chunks c JOIN items i ON i.id=c.item_id WHERE c.id=?",(row['id'],)).fetchone()
                if latest is None or latest['trashed_at'] or digest(latest)!=digest(row):continue
                blob=array.array('f',vector)
                if sys.byteorder!='little':blob.byteswap()
                db.execute('INSERT OR REPLACE INTO semantic_vectors VALUES (?,?,?,?,?)',(row['id'],sig,digest(row),len(vector),blob.tobytes()));written+=1
        return written

    def _worker(self):
        while not self.stop.is_set():
            try:
                with self.lock:self.building=config(self.archive)['enabled']
                count=self.build_batch()
                if count:
                    with self.lock:self.error=''
            except Exception as exc:
                count=0
                with self.lock:self.error=str(exc)
            finally:
                with self.lock:self.building=False
            if count:continue
            self.wake.wait(5 if not self.error else 30);self.wake.clear()

    def search(self,queries,limit=8):
        value=config(self.archive)
        if not value['enabled']:return []
        self.start();sig=signature(value)
        with self.archive.db() as db:
            available=db.execute('SELECT 1 FROM semantic_vectors WHERE signature=? LIMIT 1',(sig,)).fetchone()
        if not available:return []
        query_vectors=embed(value,queries[:4],timeout=8)
        candidates={}
        with self.archive.db() as db:
            for row in db.execute("""SELECT c.*,i.title,i.url,i.filename,v.vector,v.dimensions,v.digest FROM semantic_vectors v
                JOIN chunks c ON c.id=v.chunk_id JOIN items i ON i.id=c.item_id
                WHERE v.signature=? AND i.trashed_at=''""",(sig,)):
                if digest(row)!=row['digest']:continue
                vector=array.array('f');vector.frombytes(row['vector'])
                if sys.byteorder!='little':vector.byteswap()
                if len(vector)!=row['dimensions'] or any(not math.isfinite(v) for v in vector):continue
                scores=[sum(a*b for a,b in zip(vector,q)) for q in query_vectors if len(q)==len(vector)]
                if not scores:raise ValueError('嵌入模型维度已变化，请重建语义索引')
                score=max(scores)
                if score>=value['min_score']:
                    hit={key:row[key] for key in ('id','item_id','position','text','origin','title','url','filename')}
                    hit['origin']=json.loads(hit['origin']);hit['semantic_score']=score
                    origin=hit['origin'];key=(hit['item_id'],origin.get('batch_id'),origin.get('attachment_id'),origin.get('page'))
                    candidate=(score,hit['id'],hit)
                    if key not in candidates or candidate[:2]>candidates[key][:2]:candidates[key]=candidate
        current=config(self.archive)
        if not current['enabled'] or signature(current)!=sig:return []
        with self.lock:self.error=''
        return [hit for _,_,hit in heapq.nlargest(limit,candidates.values())]
