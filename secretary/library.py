"""Library result ranking, filters and bounded result pages."""
from datetime import datetime,timedelta,timezone

SORTS=('', 'relevance','created','updated','viewed')
STATES=('', 'ready','pending','active','error','needs_content','saved')

def rank(item,words):
    title=item['title'].casefold();tags=' '.join(item['tags']).casefold()
    return (100 if words and ' '.join(words) in title else 0)+sum(20*(word in title)+10*(word in tags)+4*(word in item.get('filename','').casefold())+2*(word in item['summary'].casefold()) for word in words)

# One indexed document per record. Trigrams preserve substring search, including
# punctuation and paths; short one/two-character terms use SQL substring checks.
FIELDS=('title','summary','text','tags','category','note','user_context','vision_text','additions','group_links','pdf_reads','url','filename')
COLUMNS="id,title,kind,url,filename,company_data,summary,tags,category,state,error,created,updated,last_viewed,favorite,pinned,trashed_at,length(text) AS text_length,note,user_context,additions,(group_links!='[]') AS has_group_links"

def document(*values):
    import json
    from .core import search_aliases
    from .rich_text import searchable_text
    from . import additions,links,pdf_reading
    row=dict(zip(FIELDS,values));batches=additions.records(row['additions'])
    content='\n'.join([str(row[name] or '') for name in ('title','summary','filename','url','category','note','user_context','vision_text')]+json.loads(row['tags'])+[searchable_text(row['text']),additions.index_text(batches),links.source(links.records(json.loads(row['group_links']))),pdf_reading.index_text(row['pdf_reads'])])
    return (content+'\n'+search_aliases(content)).casefold()

def initialize(db):
    exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='library_search'").fetchone()
    db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS library_search USING fts5(content,tokenize='trigram')")
    db.executescript('CREATE TABLE IF NOT EXISTS library_dirty(item_id TEXT PRIMARY KEY);'+
        'DROP TRIGGER IF EXISTS library_insert; DROP TRIGGER IF EXISTS library_update; DROP TRIGGER IF EXISTS library_delete;'+
        'CREATE TRIGGER library_insert AFTER INSERT ON items BEGIN INSERT OR IGNORE INTO library_dirty VALUES(new.id); END;'+
        'CREATE TRIGGER library_update AFTER UPDATE OF '+','.join(FIELDS)+' ON items BEGIN INSERT OR IGNORE INTO library_dirty VALUES(new.id); END;'+
        'CREATE TRIGGER library_delete AFTER DELETE ON items BEGIN DELETE FROM library_search WHERE rowid=old.rowid; DELETE FROM library_dirty WHERE item_id=old.id; END;'+
        'CREATE INDEX IF NOT EXISTS library_created ON items(trashed_at,created DESC);')
    if not exists:db.execute('INSERT INTO library_search(rowid,content) SELECT rowid,library_document('+','.join(FIELDS)+') FROM items')
    sync(db)

def sync(db):
    # Stored triggers use only standard SQL. Older app versions can keep writing
    # after a program rollback; this version catches up before indexed queries.
    db.execute('INSERT OR REPLACE INTO library_search(rowid,content) SELECT items.rowid,library_document('+','.join('items.'+name for name in FIELDS)+') FROM items JOIN library_dirty ON library_dirty.item_id=items.id')
    db.execute('DELETE FROM library_dirty')

def decode(row):
    import json
    from . import additions
    value=dict(row);value['tags']=json.loads(value['tags']);value['favorite']=bool(value['favorite']);value['pinned']=bool(value['pinned'])
    batches=additions.records(value.pop('additions'));value['addition_count']=len(batches);value['summary']=additions.combined_summary(value['summary'],batches)
    return value

def snippet(content,q):
    words=q.casefold().split();hits=[content.find(word) for word in words if word in content];start=max(0,min(hits,default=0)-65)
    return ('…' if start else '')+content[start:start+240]+('…' if len(content)>start+240 else '')

def query(archive,q='',category='',kind='',state='',days='',sort='',favorite='',offset=0,limit=100,active_ids=()):
    if not isinstance(q,str) or len(q)>1000 or str(favorite) not in ('','0','1') or state not in STATES or sort not in SORTS or str(days) not in ('','0','7','30','90'):raise ValueError('无效的知识库筛选选项')
    try:offset=int(offset);limit=int(limit)
    except (ValueError,TypeError):raise ValueError('无效的分页参数') from None
    if offset<0 or not 1<=limit<=100:raise ValueError('无效的分页参数')
    words=list(dict.fromkeys(q.casefold().split()))
    if len(words)>80:raise ValueError('搜索关键词过多')
    where=["trashed_at=''"];params=[]
    for name,value in (('category',category),('kind',kind)):
        if value:where.append(name+'=?');params.append(value)
    if days and int(days):where.append('created>=?');params.append((datetime.now(timezone.utc)-timedelta(days=int(days))).isoformat())
    if str(favorite)=='1':where.append('favorite=1')
    active=list(set(active_ids));active_sql=('id IN ('+','.join('?' for _ in active)+')') if active else '0'
    if state=='active':where.append('('+active_sql+" OR state IN ('processing','queued_capture','opening_browser','waiting_login','confirming_login','reading','waiting_browser_close'))");params.extend(active)
    elif state=='pending':where.append("state IN ('pending','saved') AND NOT ("+active_sql+')');params.extend(active)
    elif state:where.append('state=?');params.append(state)
    long=[word for word in words if len(word)>=3]
    if words:
        clauses=[]
        if long:clauses.append('library_search MATCH ?');params.append(' AND '.join('"'+word.replace('"','""')+'"' for word in long))
        clauses.extend('instr(content,?)>0' for _ in words);params.extend(words)
        where.append('rowid IN (SELECT rowid FROM library_search WHERE '+' AND '.join(clauses)+')')
    sql=' FROM items WHERE '+' AND '.join(where)
    order='created DESC'
    if sort in ('updated','viewed'):order=('updated' if sort=='updated' else 'last_viewed')+' DESC,created DESC'
    elif q.strip() and sort in ('','relevance'):order='library_rank(title,tags,filename,summary,additions,?) DESC,created DESC'
    elif not q.strip() and sort in ('','created'):order='pinned DESC,created DESC'
    with archive.lock,archive.db() as db:
        sync(db)
        total=db.execute('SELECT count(*)'+sql,params).fetchone()[0]
        rank_params=[q] if order.startswith('library_rank') else []
        rows=db.execute('SELECT '+COLUMNS+sql+' ORDER BY '+order+' LIMIT ? OFFSET ?',params+rank_params+[limit,offset]).fetchall()
        items=[decode(row) for row in rows]
        if words:
            for item in items:
                from . import additions,pdf_reading
                from .rich_text import searchable_text
                row=db.execute('SELECT text,pdf_reads,vision_text,note,additions FROM items WHERE id=?',(item['id'],)).fetchone()
                content=searchable_text(row['text'])+'\n'+pdf_reading.index_text(row['pdf_reads'])+'\n'+row['vision_text']+'\n'+row['note']+'\n'+additions.index_text(additions.records(row['additions']))
                if any(word in content.casefold() for word in words):
                    # Locate case-insensitively while preserving the original wording.
                    hits=[content.casefold().find(word) for word in words if word in content.casefold()];start=max(0,min(hits)-65)
                    item['search_snippet']=('…' if start else '')+content[start:start+240]+('…' if len(content)>start+240 else '')

    if words:
        hits=archive.retrieve(q,100)
        for item in items:item['source_matches']=[{'text':hit['text'][:240],'origin':hit['origin']} for hit in hits if hit['item_id']==item['id'] and hit.get('origin')][:3]
    return {'items':items,'total':total,'offset':offset,'limit':limit}

def rank_values(title,tags,filename,summary,batches,q):
    import json
    from . import additions
    return rank({'title':title,'tags':json.loads(tags),'filename':filename,'summary':additions.combined_summary(summary,additions.records(batches))},list(dict.fromkeys(q.casefold().split())))

def dashboard(archive,ids,active_ids=()):
    import re
    if not isinstance(ids,list) or len(ids)>1000 or any(not isinstance(key,str) or not re.fullmatch('[a-f0-9]{32}',key) for key in ids):raise ValueError('资料列表参数无效')
    requested=list(set(ids)|set(active_ids))
    with archive.db() as db:
        total=db.execute("SELECT count(*) FROM items WHERE trashed_at=''").fetchone()[0]
        categories=[row[0] for row in db.execute("SELECT DISTINCT category FROM items WHERE trashed_at='' ORDER BY category")]
        recent=[row[0] for row in db.execute("SELECT id FROM items WHERE trashed_at='' ORDER BY created DESC LIMIT 30")]
        keys=list(set(recent)|set(requested))
        rows=db.execute('SELECT '+COLUMNS+" FROM items WHERE trashed_at='' AND id IN ("+','.join('?' for _ in keys)+') ORDER BY created DESC',keys).fetchall() if keys else []
        states={}
        for item in requested:
            row=db.execute('SELECT updated,trashed_at FROM items WHERE id=?',(item,)).fetchone()
            states[item]={'state':'missing'} if row is None else {'state':'trashed' if row['trashed_at'] else 'available','revision':row['updated']}
    return {'items':[decode(row) for row in rows],'total':total,'categories':categories,'source_states':states}
