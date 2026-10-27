"""Real browser, owned working files and synthetic Excel bytes; OS launch is mocked."""
import base64,io,json,os,sys,tempfile,threading,zipfile
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from test_attachment_editor import sheet
from pdf_fixture import pdf_bytes
from secretary import attachment_editor as editor,bundles
from secretary.server import Service,handler

with tempfile.TemporaryDirectory() as root:
 service=Service(root);service.archive.configure('codex',False)
 parent=service.ingest({'filename':'parent.pdf','data':base64.b64encode(pdf_bytes()).decode()})['item']
 batch=service.append_material(parent['id'],{'text':'Synthetic appended workbook','attachments':[{'name':'Research workbook.xlsx','data':base64.b64encode(sheet('OldCell')).decode()}],'summarize':False,'expected_updated':parent['updated']})['item']['additions'][0]
 key=batch['attachments'][0]['id'];original=(service.archive.root/'files'/parent['id']).read_bytes()
 server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start()
 opened=[]
 try:
  with patch.object(editor,'launch',side_effect=lambda path,reveal=False:opened.append((path,reveal))),patch('secretary.ai.run') as model,sync_playwright() as pw:
   executable=os.environ.get('CHROME_PATH') or ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' if sys.platform=='darwin' else None)
   browser=pw.chromium.launch(headless=True,**({'executable_path':executable} if executable else {}))
   try:
    page=browser.new_page(viewport={'width':1280,'height':1100});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(f'http://127.0.0.1:{server.server_port}');expect(page.locator('#model-label')).to_have_text('ChatGPT · Codex')
    page.locator('#library-open').click();page.locator('#items [data-id="'+parent['id']+'"]').click()
    card=page.locator('.addition-batch .bundle-file').first
    expect(card.get_by_role('button',name='默认程序打开')).to_be_visible();card.get_by_role('button',name='默认程序打开').click()
    expect(card.get_by_role('button',name='保存修改回归档')).to_be_visible();assert opened and opened[0][0].name=='Research workbook.xlsx'
    target=opened[0][0];target.write_bytes(sheet('ChangedCell'))
    card.get_by_role('button',name='默认程序打开').click();expect(page.locator('#toast')).to_contain_text('已在默认程序中打开')
    assert target.read_bytes()==sheet('ChangedCell')
    card.get_by_role('button',name='保存修改回归档').click();expect(page.locator('#toast')).to_contain_text('文件修改已保存')
    current=service.item_detail(parent['id']);assert len(current['additions'])==1 and current['additions'][0]['id']==batch['id']
    assert 'ChangedCell' in current['additions'][0]['text'] and service.archive.retrieve('ChangedCell')
    assert (service.archive.root/'files'/parent['id']).read_bytes()==original and not model.called
    assert bundles.attachment((service.archive.root/'files'/batch['id']).read_bytes(),key)[1]==sheet('ChangedCell')
    card.get_by_role('button',name='在文件夹中显示').click();expect(page.locator('#toast')).to_contain_text('已在文件夹中显示');assert opened[-1][1] is True
    page.screenshot(path='/tmp/secretary-edit-attachment.png',full_page=True)
    page.reload();expect(page.locator('#model-label')).to_have_text('ChatGPT · Codex');page.locator('#library-open').click();page.locator('#items [data-id="'+parent['id']+'"]').click()
    expect(page.locator('.addition-batch .bundle-file').get_by_role('button',name='保存修改回归档')).to_be_visible()
    # The write endpoint requires the same local POST token as archive mutations.
    status=page.request.post(f'http://127.0.0.1:{server.server_port}/api/items/{parent["id"]}/additions/{batch["id"]}/attachments/{key}/editor/save',data={})
    assert status.status==403
    page.locator('#detail-dialog .dialog-head button').click();page.locator('#library-dialog .dialog-head button').click();page.locator('#settings-open').click();page.locator('#ui-language').select_option('en');page.locator('#settings-dialog .dialog-head button').click()
    page.locator('#library-open').click();page.locator('#items [data-id="'+parent['id']+'"]').click();expect(page.locator('.addition-batch .bundle-file').get_by_role('button',name='Save changes to archive')).to_be_visible()
    assert not errors,errors
    print('PASS: real GUI opens/reveals named attachment, preserves unsaved work, saves workbook into same appended batch and search/ZIP, preserves parent PDF, no AI call, working-copy state survives reload, POST token and English controls')
   finally:browser.close()
 finally:server.shutdown();server.server_close();service.close()
