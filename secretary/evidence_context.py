"""Bounded local context expansion, preserving archive-owned source anchors."""
import json
import re
from .core import terms

COLUMNS='c.*,i.title,i.url,i.filename,i.updated AS revision'

def expand(archive,question,queries,passages,progress=None,cancel=None):
    if not passages:return passages,0,[]
    result=list(passages);seen={str(p['id']) for p in passages};chars=sum(len(p['text']) for p in passages);notice=[]
    def check():
        if cancel and cancel.is_set():
            from .ai import ModelCancelledError
            raise ModelCancelledError('问答已停止。')
    def add(row):
        nonlocal chars
        if not row or str(row['id']) in seen or len(result)>=20 or chars>=24000:return
        hit=dict(row)
        if isinstance(hit['origin'],str):hit['origin']=json.loads(hit['origin'])
        hit['text']=hit['text'][:max(0,24000-chars)]
        if not hit['text'].strip():return
        chars+=len(hit['text']);seen.add(str(hit['id']));result.append(hit)
    ids=list(dict.fromkeys(p['item_id'] for p in passages))[:3]
    tokens=list(dict.fromkeys(terms(question+' '+' '.join(queries))))[:80]
    with archive.db() as db:
        long=[item for item in ids if db.execute("SELECT count(*) FROM chunks WHERE item_id=?",(item,)).fetchone()[0]>4]
        pdf_hits=[p for p in passages if p.get('origin',{}).get('page') and str(p.get('origin',{}).get('name','')).lower().endswith('.pdf')][:2]
        if not long and not pdf_hits:return result,0,notice
        if progress:progress('expanding',len(set(long)|{p['item_id'] for p in pdf_hits}))
        for item in long:
            check()
            if tokens:
                match=' OR '.join('"'+token.replace('"','""')+'"' for token in tokens)
                rows=db.execute('SELECT '+COLUMNS+" FROM search JOIN chunks c ON c.id=search.chunk_id JOIN items i ON i.id=c.item_id WHERE search MATCH ? AND c.item_id=? AND i.trashed_at='' ORDER BY bm25(search) LIMIT 64",(match,item)).fetchall()
                # Document-title terms appear in every FTS chunk. Prioritize matches
                # in the actual body before selecting two additional sections.
                ranked=sorted(rows,key=lambda row:sum(token in row['text'].casefold() for token in tokens),reverse=True)
                for row in ranked[:2]:add(row)
            anchors=[p for p in result if p['item_id']==item][:4]
            for hit in anchors:
                check()
                stored=db.execute('SELECT origin FROM chunks WHERE id=?',(hit['id'],)).fetchone()
                origin=stored[0] if stored else json.dumps(hit.get('origin',{}),ensure_ascii=False)
                # The stored JSON may use different spacing; source identity is
                # checked after a small SQL window, never supplied by the model.
                for direction in ('<','>'):
                    row=db.execute('SELECT '+COLUMNS+f" FROM chunks c JOIN items i ON i.id=c.item_id WHERE c.item_id=? AND c.id {direction} ? AND c.origin=? AND i.trashed_at='' ORDER BY c.id "+('DESC' if direction=='<' else 'ASC')+' LIMIT 1',(item,hit['id'],origin)).fetchone()
                    add(row)
    # Read at most two adjacent PDF pages directly, without altering indexed
    # ranges, summaries or invoking OCR. Unreadable scans retain an honest limit.
    from . import pdf_reading,pdf_preview
    from .answer_cache import files
    page_keys={(p['item_id'],p.get('origin',{}).get('batch_id',''),p.get('origin',{}).get('attachment_id',''),p.get('origin',{}).get('page')) for p in result}
    read=0
    for hit in pdf_hits:
        if read>=2 or chars>=24000:break
        origin=hit['origin'];item=hit['item_id'];batch=origin.get('batch_id','');attachment=origin.get('attachment_id','')
        try:
            check();before=files(archive,[item])
            _,source,name,digest,_=pdf_reading.owned(archive,item,batch,attachment)
            total=pdf_preview.info(source)
            for number in (origin['page']-1,origin['page']+1):
                identity=(item,batch,attachment,number)
                if number<1 or number>total or identity in page_keys or read>=2 or chars>=24000:continue
                check();value=pdf_preview.inspect(source,number,number,False,cancel=lambda:bool(cancel and cancel.is_set()))
                check()
                if before is None or before!=files(archive,[item]):raise ValueError('PDF 原件已变化，请重新核对')
                read+=1;page_keys.add(identity);page=value['pages'][0]
                if not page['text'].strip():notice.append('相邻 PDF 页面没有可提取文字，可按页 OCR 后再核对。');continue
                add(dict(hit,id=f'pdf:{item}:{batch}:{attachment}:{number}',text='【相邻页节选】\n'+page['text'],origin={**origin,'page':number,'name':name,'digest':digest,'method':'text'}))
        except (OSError,ValueError,KeyError,RuntimeError):
            check();notice.append('部分相邻 PDF 页面未能读取，本次仅依据已取得的内容回答。')
    return result,len(result)-len(passages),list(dict.fromkeys(notice))
