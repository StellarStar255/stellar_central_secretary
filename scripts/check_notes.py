"""Exercise quick-note autosave and compatibility with existing note images."""
import base64,io,os,sys,tempfile,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary.server import Service,handler
from playwright.sync_api import sync_playwright,expect
stream=io.BytesIO();Image.new('RGB',(12,12),'#77aacc').save(stream,format='PNG');encoded=base64.b64encode(stream.getvalue()).decode()
with tempfile.TemporaryDirectory() as root:
 service=Service(root);service.archive.configure('codex',False);item,_=service.archive.add('Fixture','Original body.')
 server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with patch.object(service,'queue') as queue,patch('secretary.attachment_editor.launch') as launch,sync_playwright() as pw:
   browser=pw.chromium.launch(headless=True,**({'executable_path':os.environ.get('CHROME_PATH') or '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'} if os.environ.get('CHROME_PATH') or sys.platform=='darwin' else {}))
   try:
    page=browser.new_page(viewport={'width':1100,'height':950});errors=[];page.on('pageerror',lambda error:(errors.append(str(error)),print('PAGE ERROR:',error,flush=True)))
    page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#library-open').click();page.locator('#items [data-id="'+item+'"]').click();page.locator('#preview-full').click()
    assert page.locator('.quick-note').bounding_box()['y']<page.locator('#detail-content h3').filter(has_text='资料摘要').bounding_box()['y']
    page.locator('#note-text').fill('这是一条自己的速记 PersonalMemoUnique');expect(page.locator('#note-status')).to_have_text('已保存',timeout=10000)
    assert service.archive.get(item)['note']=='这是一条自己的速记 PersonalMemoUnique'
    page.evaluate('''async ([id,data])=>{const item=await api('/api/items/'+id);await api('/api/items/'+id+'/notes',{text:item.note,images:[{name:'legacy.png',data}],version:item.note_version});await detail(item.id)}''',[item,encoded])
    expect(page.locator('#note-images img')).to_have_count(1);expect(page.locator('#note-images img')).to_have_attribute('src',__import__('re').compile(r'^/api/items/'),timeout=10000)
    expect(page.locator('#note-status')).to_have_text('已保存');saved=service.archive.get(item);assert len(saved['note_images'])==1
    response=page.request.get(f'http://127.0.0.1:{server.server_port}/api/items/{item}/note-images/'+saved['note_images'][0]['id']);assert response.ok and response.body()==stream.getvalue()
    assert page.locator('#note-images a').count()==0
    page.locator('[data-note-open]').click();expect(page.locator('#image-viewer')).to_be_visible()
    page.wait_for_function("()=>document.querySelector('#image-viewer img').naturalWidth===12")
    assert len(browser.contexts[0].pages)==1 and launch.call_count==0
    page.locator('[data-viewer="in"]').click();expect(page.locator('[data-viewer="zoom"]')).to_have_text('125%')
    page.keyboard.press('Escape');expect(page.locator('#image-viewer')).not_to_be_visible();expect(page.locator('#detail-dialog')).to_be_visible()
    page.evaluate('''async ([id,data])=>{const item=await api('/api/items/'+id);await api('/api/items/'+id+'/notes',{text:item.note,images:[...item.note_images.map(image=>({id:image.id})),{name:'legacy2.png',data}],version:item.note_version});await detail(item.id)}''',[item,encoded])
    expect(page.locator('#note-images img')).to_have_count(2);expect(page.locator('#note-status')).to_have_text('已保存');assert page.locator('#drag-overlay').is_hidden();assert page.evaluate('attachedFiles.length')==0
    page.locator('[data-note-open]').first.click();expect(page.locator('#image-viewer-caption')).to_contain_text('1 / 2')
    page.keyboard.press('ArrowRight');expect(page.locator('#image-viewer-caption')).to_contain_text('2 / 2')
    page.keyboard.press('ArrowLeft');expect(page.locator('#image-viewer-caption')).to_contain_text('1 / 2')
    page.locator('[data-viewer="in"]').click()
    stage=page.locator('.image-viewer-stage');box=stage.bounding_box();page.mouse.move(box['x']+100,box['y']+100);page.mouse.down();page.mouse.move(box['x']+150,box['y']+130);page.mouse.up()
    assert 'translate(50px,30px)' in page.locator('#image-viewer img').get_attribute('style').replace(' ', '')
    page.locator('[data-viewer="zoom"]').click();expect(page.locator('[data-viewer="zoom"]')).to_have_text('100%')
    page.screenshot(path='/tmp/secretary-image-viewer.png');page.keyboard.press('Escape');assert launch.call_count==0
    service.archive.update(item,summary='AI-generated summary',tags=['AI tag']);page.evaluate('refresh()');expect(page.locator('#note-text')).to_have_value(saved['note'])
    page.reload();page.locator('#library-open').click();page.locator('#search').fill('PersonalMemoUnique');expect(page.locator('#items .library-row')).to_have_count(1);page.locator('#items [data-id="'+item+'"]').click();page.locator('#preview-full').click();expect(page.locator('#note-images img')).to_have_count(2)
    page.wait_for_function("()=>document.querySelector('#note-images img')?.naturalWidth>0");page.screenshot(path='/tmp/secretary-quick-notes-zh.png');page.locator('[data-note-remove]').first.click();expect(page.locator('#note-images img')).to_have_count(1);expect(page.locator('#note-status')).to_have_text('已保存');page.locator('[data-note-remove]').click();expect(page.locator('#note-images img')).to_have_count(0);expect(page.locator('#note-status')).to_have_text('已保存');assert not service.archive.get(item)['note_images']
    page.locator('#detail-dialog .dialog-head button').click();page.locator('#library-dialog .dialog-head button').click();page.locator('#settings-open').click();page.locator('#ui-language').select_option('en');expect(page.locator('html')).to_have_attribute('lang','en');page.locator('#settings-dialog .dialog-head button').click();page.locator('#library-open').click();page.locator('#items [data-id="'+item+'"]').click();page.locator('#preview-full').click()
    expect(page.locator('.quick-note h3')).to_have_text('My quick notes');expect(page.locator('#note-status')).to_have_text('Saved');expect(page.locator('#note-save')).to_have_text('Save notes');assert not errors,errors;queue.assert_not_called()
    assert service.archive.get(item)['text']=='Original body.'
    print('PASS: quick-note placement, autosaved text, existing note-image compatibility and authenticated local image display, built-in viewer, zoom, pan, gallery arrows, Esc preserves details without external launch or new tab, reload persistence, note keyword search, AI updates preserve notes, image removal, Chinese/English labels, zero AI calls and original body unchanged')
   finally:browser.close()
 finally:server.shutdown();server.server_close();service.close()
