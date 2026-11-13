"""Archive synthetic command/knowledge text through the real composer; never execute it."""
import os,sys,tempfile,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from playwright.sync_api import sync_playwright,expect
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary.server import Service,handler

with tempfile.TemporaryDirectory() as root:
 service=Service(root);service.archive.configure('codex',False)
 server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with patch.object(service,'ask',side_effect=AssertionError('Text questions must use the conversation pipeline')),patch.object(service,'ask_library',return_value={'answer':'Synthetic question answer.','sources':[]}) as ask,patch('secretary.server.fetch_page',side_effect=AssertionError('Command URLs must not be fetched')) as fetch,sync_playwright() as pw:
   executable=os.environ.get('CHROME_PATH') or ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' if sys.platform=='darwin' else None)
   browser=pw.chromium.launch(headless=True,**({'executable_path':executable} if executable else {}))
   try:
    page=browser.new_page(viewport={'width':1200,'height':950});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(f'http://127.0.0.1:{server.server_port}');expect(page.locator('#model-label')).to_have_text('ChatGPT · Codex')
    sentinel=Path(root)/'command-must-not-run'
    command=f'cd /mnt/data/example\n  touch "{sentinel}"\n  tar -czf samples.tar.gz samples/'
    samples=[command,'curl https://example.invalid/data?format=json','```bash\necho "what?"\n```','量化校准集应覆盖实际输入分布。']
    for index,text in enumerate(samples,1):
     page.locator('#message-input').fill(text);page.locator('#send-button').click()
     expect(page.locator('#messages .archive-card')).to_have_count(index)
     expect(page.locator('#send-button')).to_be_disabled() # empty composer after completed send
    assert not sentinel.exists() and not ask.called and not fetch.called
    items=[service.archive.get(item["id"]) for item in service.archive.list()];assert len(items)==4
    item=next(item for item in items if item['text']==command);assert item['title']=='cd /mnt/data/example' and item['kind']=='note'
    assert service.archive.retrieve('tar samples')
    page.reload();expect(page.locator('#messages .archive-card')).to_have_count(4)
    page.locator('#library-open').click();page.locator('#search').fill('tar samples')
    page.locator('#items [data-id="'+item['id']+'"]').click();page.locator('#preview-full').click();expect(page.locator('#detail-content')).to_contain_text('tar -czf samples.tar.gz samples/')
    page.screenshot(path='/tmp/secretary-command-archive.png')
    page.locator('#detail-dialog .dialog-head button').click();page.locator('#library-dialog .dialog-head button').click()
    page.locator('#input-mode').select_option('ask');page.locator('#message-input').fill('这条命令如何使用？');page.locator('#send-button').click()
    expect(page.locator('#messages')).to_contain_text('Synthetic question answer.');assert ask.call_count==1 and len(service.archive.list())==4
    page.locator('#input-mode').select_option('note');page.locator('#message-input').fill('为什么命令需要引号？');page.locator('#send-button').click()
    expect(page.locator('#messages .archive-card')).to_have_count(5);assert ask.call_count==1
    for index,mode in enumerate(['auto','library','ask'],6):
     text='建档：\n周六上午11:00带测试对象去复查 '+mode
     page.locator('#input-mode').select_option(mode);page.locator('#message-input').fill(text);page.locator('#send-button').click()
     expect(page.locator('#messages .archive-card')).to_have_count(index)
     assert ask.call_count==1,'An explicit save must not call the answering model'
     found=[service.archive.get(item['id']) for item in service.archive.list() if service.archive.get(item['id'])['text']==text]
     assert len(found)==1 and '年' in found[0]['title'] and '月' in found[0]['title'],found
     assert found[0]['user_context'].startswith('【日期解析】')
     resolved=found[0]['user_context'].split('\n',2)[-1]
     expect(page.locator('#messages .message.assistant').last).to_contain_text(resolved)
     assert any(hit['item_id']==found[0]['id'] for hit in service.archive.retrieve('测试对象'))
    page.reload();expect(page.locator('#messages .archive-card')).to_have_count(8)
    page.locator('#input-mode').select_option('auto');page.locator('#message-input').fill('建档功能怎么用？');page.locator('#send-button').click()
    expect(page.locator('#messages .message.assistant').last).to_contain_text('Synthetic question answer.')
    assert ask.call_count==2 and len(service.archive.list())==8
    page.route('**/api/ingest',lambda route:route.fulfill(status=500,content_type='application/json',body='{"error":"Synthetic save failure"}'))
    failed='建档：\n保存失败时应保留这段测试内容'
    page.locator('#message-input').fill(failed);page.locator('#send-button').click()
    expect(page.locator('#messages .message.assistant').last).to_contain_text('Synthetic save failure')
    expect(page.locator('#message-input')).to_have_value(failed)
    expect(page.locator('#messages .archive-card')).to_have_count(8)
    assert ask.call_count==2 and len(service.archive.list())==8
    page.unroute('**/api/ingest')
    page.locator('#new-chat').click();page.locator('#input-mode').select_option('library')
    arrangement='周六上午11:00带测试对象去复查 contextual-save'
    page.locator('#message-input').fill(arrangement);page.locator('#send-button').click()
    expect(page.locator('#messages .message.assistant').last).to_contain_text('Synthetic question answer.')
    with page.expect_request(lambda request:request.url.endswith('/api/ingest')) as saved_request:
     page.locator('#message-input').fill('建档');page.locator('#send-button').click()
    expect(page.locator('#messages .archive-card')).to_have_count(1)
    payload=saved_request.value.post_data_json;assert payload['text']==arrangement and payload.get('note_reference')
    contextual=service.archive.get(service.archive.list(q='contextual-save')[0]['id'])
    assert contextual['text']==arrangement and contextual['user_context'].startswith('【日期解析】')
    expect(page.locator('#messages .message.assistant').last).to_contain_text(contextual['user_context'].split('\n',2)[-1])
    page.screenshot(path='/tmp/stellar-contextual-save.png')
    page.locator('#new-chat').click();page.locator('#message-input').fill('建档');page.locator('#send-button').click()
    expect(page.locator('#messages .message.assistant').last).to_contain_text('没有找到可建档的上一条文字')
    assert len(service.archive.list())==9
    page.route('**/api/ingest',lambda route:route.abort('connectionrefused'))
    disconnected='建档：网络中断时保留测试内容'
    page.locator('#message-input').fill(disconnected);page.locator('#send-button').click()
    expect(page.locator('#messages .message.assistant').last).to_contain_text('本地服务连接中断')
    expect(page.locator('#message-input')).to_have_value(disconnected)
    expect(page.locator('#messages .archive-card')).to_have_count(0)
    assert len(service.archive.list())==9
    print('PASS: bare 建档 saves the prior user arrangement, retains the original timestamp, shows its resolved date, and never archives an empty command in a new chat')
    print('PASS: explicit 建档 saves during active dialogue in auto/library/ask; raw arrangement preserved, meaningful title, searchable and reload-persistent; archive-help questions remain questions; failed save preserves input without false success')
    assert not errors,errors
    print('PASS: real GUI auto-archives literal commands, command URLs and knowledge; no execution, fetch or retrieval; searchable persistent originals, meaningful title and manual ask/archive overrides')
   finally:browser.close()
 finally:server.shutdown();server.server_close();service.close()
