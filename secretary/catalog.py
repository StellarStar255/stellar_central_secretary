"""Complete keyword-based record enumeration, independent of QA excerpt limits."""
def page(archive,queries,offset=0,limit=20):
    if not isinstance(queries,list) or not 1<=len(queries)<=3 or any(not isinstance(q,str) or not q.strip() or len(q)>200 for q in queries):raise ValueError('资料清单检索词无效')
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=50:raise ValueError('资料清单页码无效')
    queries=list(dict.fromkeys(q.strip() for q in queries));found={}
    for query in queries:
        for item in archive.list(q=query):found.setdefault(item['id'],item)
    notice=''
    if not found:
        import re
        subjects=list(dict.fromkeys(re.sub(r'(?:的)?(?:历史|史)$|\s+history$','',query,flags=re.I).strip() for query in queries))
        subjects=[query for query in subjects if len(query)>=2 and query not in queries]
        if subjects:
            queries=list(dict.fromkeys(subjects+queries))[:3]
            for query in queries:
                for item in archive.list(q=query):found.setdefault(item['id'],item)
            if found:notice='完整主题词未命中，已按主体关键词补查；请核对清单范围。'
    matches=sorted(found.values(),key=lambda i:(i['created'],i['id']),reverse=True)
    selected=matches[offset:offset+limit]
    sources=[{'number':index+1,'item_id':item['id'],'title':item['title'],'url':item['url'],'revision':item['updated'],
              'text':item.get('search_snippet',''),'origin':{}} for index,item in enumerate(selected)]
    return {'answer':'按关键词匹配，共找到 '+str(len(matches))+' 条资料。清单可翻页查看；这是关键词匹配范围，不代表全部语义相关资料。',
            'sources':sources,'catalog':{'queries':queries,'total':len(matches),'offset':offset,'limit':limit},'retrieval_notice':notice}
