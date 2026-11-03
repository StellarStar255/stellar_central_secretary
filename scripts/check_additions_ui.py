"""Synthetic append UI regression. No live model or real user data."""
import base64,io,json,os,sys,tempfile,threading,time
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from PIL import Image
from playwright.sync_api import sync_playwright,expect
from secretary.server import Service,handler
from secretary import ai,attachment_editor as editor

stream=io.BytesIO();Image.new('RGB',(60,40),'blue').save(stream,format='PNG');png=stream.getvalue()
with tempfile.TemporaryDirectory() as root:
 service=Service(root);service.archive.configure('codex',False)
 item_id,_=service.archive.add('Original archive','Original paper text',filename='paper.txt',data=b'Original paper text')
 service.archive.update(item_id,summary='Original summary retained')
 server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
 try:
  with patch.object(ai,'run',return_value=json.dumps({'summary':'New supplemental findings','vision_text':'SyntheticBlueDiagram','tags':[]})) as model,patch.object(editor,'launch') as launched,sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path=os.environ.get('CHROME_PATH') or ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' if sys.platform=='darwin' else None),headless=True)
   try:
    page=browser.new_page(viewport={'width':1280,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(base);expect(page.locator('#model-label')).to_have_text('ChatGPT · Codex',timeout=15000)
    page.locator('#recent-items [data-id="'+item_id+'"]').click();page.locator('#append-material').click()
    page.locator('#append-text').fill('New experiment details ')
    page.locator('#append-text').evaluate('(input)=>input.setSelectionRange(input.value.length,input.value.length)')
    page.evaluate('''data=>{const d=new DataTransfer();d.items.add(new File([Uint8Array.from(atob(data),c=>c.charCodeAt(0))],'new.png',{type:'image/png'}));d.setData('text/plain','Clipboard annotation');document.querySelector('#append-text').dispatchEvent(new ClipboardEvent('paste',{clipboardData:d,bubbles:true,cancelable:true}))}''',base64.b64encode(png).decode())
    expect(page.locator('#append-files img')).to_be_visible();expect(page.locator('#append-text')).to_have_value('New experiment details Clipboard annotation')
    page.locator('#append-file-input').set_input_files({'name':'context.txt','mimeType':'text/plain','buffer':b'New supplementary context'})
    page.locator('#append-dialog .dialog-head button').click();page.locator('#append-material').click()
    expect(page.locator('#append-text')).to_have_value('New experiment details Clipboard annotation')
    page.locator('#append-summarize').check();page.locator('#append-save').click()
    expect(page.locator('#append-dialog')).not_to_be_visible()
    expect(page.locator('#detail-content')).to_contain_text('New supplemental findings',timeout=15000)
    expect(page.locator('#detail-content')).to_contain_text('Original summary retained')
    assert len(service.archive.list())==1 and model.call_count==1
    saved=service.archive.get(item_id);assert saved['title']=='Original archive' and saved['text']=='Original paper text'
    assert page.request.get(base+'/api/items/'+item_id+'/file').body()==b'Original paper text'
    batch=service.item_detail(item_id)['additions'][0];attachment=batch['attachments'][0]
    assert page.request.get(base+'/api/items/'+item_id+'/additions/'+batch['id']+'/attachments/'+attachment['id']+'/preview').body()==png
    page.locator('.addition-batch .bundle-file img').click();expect(page.locator('#toast')).to_have_text('已在默认程序中打开图片');assert launched.call_count==1 and launched.call_args.args[0].name=='new.png' and launched.call_args.args[0].read_bytes()==png;assert len(browser.contexts[0].pages)==1
    page.screenshot(path='/tmp/secretary-append-materials.png')
    page.reload();page.locator('#recent-items [data-id="'+item_id+'"]').click();expect(page.locator('.addition-batch')).to_have_count(1)
    page.locator('#append-material').click();page.locator('#append-text').fill('Second batch, text only');page.locator('#append-summarize').uncheck();page.locator('#append-save').click()
    expect(page.locator('.addition-batch')).to_have_count(2);assert model.call_count==1
    assert service.archive.list(q='Second batch')[0]['id']==item_id and not errors,errors
    page.locator('#append-material').click();page.locator('#append-text').fill('Private pending supplementary draft')
    page.locator('#append-dialog .dialog-head button').click();page.locator('#detail-dialog .dialog-head button').click()
    page.locator('#recent-items [data-id="'+item_id+'"]').click(button='right');page.locator('#archive-delete-menu').click();page.locator('#delete-archive-confirm').click()
    expect(page.locator('#toast')).to_contain_text('已移到回收站');page.evaluate('''async()=>{const data=await api('/api/trash');for(const item of data.items){const result=await api('/api/trash/'+item.id+'/purge',{confirmed:true,expected_updated:item.updated,expected_trashed_at:item.trashed_at});StellarArchiveActions.accept(result.history);mergeChats(result.history)}await refresh();toast('归档已删除')}''')
    expect(page.locator('#toast')).to_have_text('归档已删除');expect(page.locator('#append-text')).to_have_value('')
    assert not list((Path(root)/'files').iterdir()) and not errors,errors
    print('PASS: paste image+clipboard text+file into existing archive; cancel/reopen draft; one incremental model call; old title/text/summary/original intact; attachment preview; reload; second text-only batch without cloud call; parent deletion clears batches and pending append draft')
   except Exception:
    print({'page_errors':errors,'toast':page.locator('#toast').inner_text()},flush=True);raise
   finally:browser.close()
 finally:service.close();server.shutdown();server.server_close()
