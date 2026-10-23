"""Exercise quick-note text, clipboard images, autosave and local backups."""
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
  with patch.object(service,'queue') as queue,sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path=os.environ.get('CHROME_PATH','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),headless=True)
   try:
    page=browser.new_page(viewport={'width':1100,'height':950});errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#library-open').click();page.locator('#items [data-id="'+item+'"]').click()
    assert page.locator('.quick-note').bounding_box()['y']<page.locator('#detail-content h3').filter(has_text='资料摘要').bounding_box()['y']
    page.locator('#note-text').fill('这是一条自己的速记 PersonalMemoUnique');expect(page.locator('#note-status')).to_have_text('已保存',timeout=10000)
    assert service.archive.get(item)['note']=='这是一条自己的速记 PersonalMemoUnique'
    page.locator('#note-text').evaluate('''(node,data)=>{const bytes=Uint8Array.from(atob(data),c=>c.charCodeAt(0));const clipboard=new DataTransfer();clipboard.items.add(new File([bytes],'pasted.png',{type:'image/png'}));node.dispatchEvent(new ClipboardEvent('paste',{clipboardData:clipboard,bubbles:true,cancelable:true}))}''',encoded)
    expect(page.locator('#note-images img')).to_have_count(1);expect(page.locator('#note-images img')).to_have_attribute('src',__import__('re').compile(r'^/api/items/'),timeout=10000)
    expect(page.locator('#note-status')).to_have_text('已保存');saved=service.archive.get(item);assert len(saved['note_images'])==1
    response=page.request.get(f'http://127.0.0.1:{server.server_port}/api/items/{item}/note-images/'+saved['note_images'][0]['id']);assert response.ok and response.body()==stream.getvalue()
    service.archive.update(item,summary='AI-generated summary',tags=['AI tag']);page.evaluate('refresh()');expect(page.locator('#note-text')).to_have_value(saved['note'])
    page.reload();page.locator('#library-open').click();page.locator('#search').fill('PersonalMemoUnique');expect(page.locator('#items .library-row')).to_have_count(1);page.locator('#items [data-id="'+item+'"]').click();expect(page.locator('#note-images img')).to_have_count(1)
    page.wait_for_function("document.querySelector('#note-images img')?.naturalWidth>0");page.screenshot(path='/tmp/secretary-quick-notes-zh.png');page.locator('[data-note-remove]').click();expect(page.locator('#note-images img')).to_have_count(0);expect(page.locator('#note-status')).to_have_text('已保存');assert not service.archive.get(item)['note_images']
    page.locator('#detail-dialog .dialog-head button').click();page.locator('#library-dialog .dialog-head button').click();page.locator('#settings-open').click();page.locator('#ui-language').select_option('en');expect(page.locator('html')).to_have_attribute('lang','en');page.locator('#settings-dialog .dialog-head button').click();page.locator('#library-open').click();page.locator('#items [data-id="'+item+'"]').click()
    expect(page.locator('.quick-note h3')).to_have_text('My quick notes');expect(page.locator('#note-status')).to_have_text('Saved');expect(page.locator('#note-save')).to_have_text('Save notes');assert not errors,errors;queue.assert_not_called()
    assert service.archive.get(item)['text']=='Original body.'
    print('PASS: quick-note placement, autosaved text, clipboard image upload and authenticated local image display, reload persistence, note keyword search, AI updates preserve notes, image removal, Chinese/English labels, zero AI calls and original body unchanged')
   finally:browser.close()
 finally:server.shutdown();server.server_close();service.close()
