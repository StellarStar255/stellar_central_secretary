"""Verify repeated archived arrangements use the real background path, without AI."""
import os,sys,tempfile,threading,time
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary.server import Service,handler
from secretary import ai
from playwright.sync_api import sync_playwright,expect

with tempfile.TemporaryDirectory() as root:
    service=Service(root);service.archive.configure('codex',False)
    text='周六上午11:00带测试对象去复查'
    item=service.ingest({'text':text,'archive_only':True})['item']
    table,_=service.archive.add('Synthetic timetable','周六上午课程表，测试旧话题隔离')
    service.chat_history({'activeId':'fixture-chat','conversations':[{'id':'fixture-chat','title':'Synthetic archived arrangement','updated':1,'messages':[
        {'id':'old-question','role':'user','text':'周六有课吗？','knowledgeQuestion':True},
        {'id':'old-answer','role':'assistant','text':'原来的课程表记录。[1]','sources':[{'number':1,'item_id':table,'title':'Synthetic timetable'}]},
        {'id':'old-condition','role':'user','text':'这个课程表就是她的，依据这张表判断','knowledgeQuestion':True},
        {'id':'old-condition-answer','role':'assistant','text':'已按指定条件核对课程表。','sources':[{'number':1,'item_id':table,'title':'Synthetic timetable'}]}
    ]}]})
    server=ThreadingHTTPServer(('127.0.0.1',0),handler(service))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with patch.object(ai,'run',side_effect=AssertionError('Exact archive matches must not call AI')),sync_playwright() as pw:
            executable=os.environ.get('CHROME_PATH') or ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' if sys.platform=='darwin' else None)
            browser=pw.chromium.launch(headless=True,**({'executable_path':executable} if executable else {}))
            try:
                page=browser.new_page(viewport={'width':1300,'height':950});errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#input-mode').select_option('library')
                durations=[]
                for index in range(2):
                    started=time.monotonic();page.locator('#message-input').fill(text);page.locator('#send-button').click()
                    answer=page.locator('#messages .message.assistant').last
                    expect(answer).to_contain_text('这条安排已归档：')
                    expect(answer.locator('.answer-timing summary')).to_contain_text('直接读取归档')
                    expect(answer).to_contain_text(item['user_context'].split('\n',2)[-1])
                    expect(answer).not_to_contain_text('课程表')
                    expect(answer).not_to_contain_text('冲突')
                    durations.append(round(time.monotonic()-started,3))
                    expect(page.locator('#composer-status')).to_have_text('')
                page.screenshot(path='/tmp/stellar-direct-archive-reply.png')
                saved=service.chat_history();replies=[message for chat in saved['conversations'] for message in chat['messages'] if message.get('timings',{}).get('archive_match')]
                assert len(replies)==2 and all(message['timings']['model_calls']==0 and [source['item_id'] for source in message['sources']]==[item['id']] for message in replies)
                assert not errors,errors
                print('PASS: repeated exact arrangements use live archive citations through background jobs; zero model calls; browser end-to-end seconds:',durations)
            finally:browser.close()
    finally:server.shutdown();server.server_close();service.close()
