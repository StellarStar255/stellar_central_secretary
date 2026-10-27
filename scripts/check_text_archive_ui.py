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
  with patch.object(service,'ask',return_value={'answer':'Synthetic question answer.','sources':[]}) as ask,patch('secretary.server.fetch_page',side_effect=AssertionError('Command URLs must not be fetched')) as fetch,sync_playwright() as pw:
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
    page.locator('#items [data-id="'+item['id']+'"]').click();expect(page.locator('#detail-content')).to_contain_text('tar -czf samples.tar.gz samples/')
    page.screenshot(path='/tmp/secretary-command-archive.png')
    page.locator('#detail-dialog .dialog-head button').click();page.locator('#library-dialog .dialog-head button').click()
    page.locator('#input-mode').select_option('ask');page.locator('#message-input').fill('这条命令如何使用？');page.locator('#send-button').click()
    expect(page.locator('#messages')).to_contain_text('Synthetic question answer.');assert ask.call_count==1 and len(service.archive.list())==4
    page.locator('#input-mode').select_option('note');page.locator('#message-input').fill('为什么命令需要引号？');page.locator('#send-button').click()
    expect(page.locator('#messages .archive-card')).to_have_count(5);assert ask.call_count==1
    assert not errors,errors
    print('PASS: real GUI auto-archives literal commands, command URLs and knowledge; no execution, fetch or retrieval; searchable persistent originals, meaningful title and manual ask/archive overrides')
   finally:browser.close()
 finally:server.shutdown();server.server_close();service.close()
