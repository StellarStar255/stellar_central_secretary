"""Real drag/keyboard ordering across batches, durable preview order and rollback."""
import base64,io,os,sys,tempfile,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from PIL import Image
from playwright.sync_api import sync_playwright,expect
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary.server import Service,handler
from secretary import bundles,attachment_order

def image(color):
 stream=io.BytesIO();Image.new('RGB',(48,32),color).save(stream,format='PNG');return stream.getvalue()
def file(name,data):return {'name':name,'data':base64.b64encode(data).decode()}
with tempfile.TemporaryDirectory() as root:
 service=Service(root);service.archive.configure('codex',False)
 raw,_=bundles.create('',[file('同名.png',image('red')),file('说明.txt',b'NOTE-FILE')]);ident,_=service.archive.add('Sort target','Original prose',filename='materials.stellar.zip',data=raw);bundles.cleanup(raw)
 service.append_material(ident,{'attachments':[file('同名.png',image('blue')),file('短片.mp4',b'VIDEO-ORIGINAL')],'summarize':False,'expected_updated':service.archive.get(ident)['updated']})
 service.archive.update(ident,summary='Preserved summary',state='ready')
 original=service.item_detail(ident);initial=[attachment_order.key(value) for value in original['all_attachments']]
 before={path.name:path.read_bytes() for path in (Path(root)/'files').iterdir() if path.is_file()}
 server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with patch('secretary.ai.analyze_material') as analyze,sync_playwright() as pw:
   browser=pw.chromium.launch(headless=True,**({'executable_path':os.environ.get('CHROME_PATH') or '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'} if os.environ.get('CHROME_PATH') or sys.platform=='darwin' else {}))
   try:
    page=browser.new_page(viewport={'width':1250,'height':1000});errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    base=f'http://127.0.0.1:{server.server_port}';page.goto(base);page.locator('#library-open').click();page.locator('#items [data-id="'+ident+'"]').click();page.locator('#preview-full').click()
    def order(selector='#detail-attachments'):
     return page.locator(selector+' .material-card').evaluate_all("nodes=>nodes.map(node=>(node.dataset.batch||'original')+':'+node.dataset.attachment)")
    def stored():return [attachment_order.key(value) for value in service.item_detail(ident)['all_attachments']]
    # Actual HTML drag, using the visible handle, crosses original and added batches.
    page.locator('#detail-attachments [data-order-handle]').first.drag_to(page.locator('#detail-attachments [data-order-handle]').last)
    expect(page.locator('#detail-attachments [data-order-status]')).to_have_text('附件顺序已保存')
    expected=initial[1:]+initial[:1];assert order()==expected and stored()==expected
    assert not page.locator('#image-viewer').is_visible() and not page.locator('#video-viewer').is_visible()
    assert page.evaluate('attachedFiles.length')==0
    # Keyboard reordering is accessible and does not overwrite active title/note drafts.
    page.locator('#note-text').fill('Independent note draft')
    page.locator('#edit-title').click();page.locator('#rename-title').fill('Independent title draft')
    handle=page.locator('#detail-attachments [data-order-handle]').last;handle.focus();handle.press('ArrowLeft')
    expect(page.locator('#detail-attachments [data-order-status]')).to_have_text('附件顺序已保存')
    expected[-1],expected[-2]=expected[-2],expected[-1]
    assert order()==expected and stored()==expected
    expect(page.locator('#rename-title')).to_have_value('Independent title draft');expect(page.locator('#note-text')).to_have_value('Independent note draft')
    # Failed save rolls back the optimistic arrangement; no archive/file mutation.
    page.route('**/attachment-order',lambda route:route.fulfill(status=409,content_type='application/json',body='{"error":"Synthetic order conflict"}'))
    page.locator('#detail-attachments [data-order-handle]').first.focus();page.keyboard.press('ArrowRight')
    expect(page.locator('#detail-attachments [data-order-status]')).to_contain_text('Synthetic order conflict')
    assert order()==expected and stored()==expected;page.unroute('**/attachment-order')
    page.locator('#cancel-title').click()
    # Cancelling a drag outside the catalogue does not save an order.
    calls=[];page.on('request',lambda request:calls.append(request.url) if request.method=='POST' and request.url.endswith('/attachment-order') else None)
    handle=page.locator('#detail-attachments [data-order-handle]').first;handle.scroll_into_view_if_needed();box=handle.bounding_box();page.mouse.move(box['x']+8,box['y']+8);page.mouse.down();page.mouse.move(box['x']+40,box['y']+8,steps=5);page.keyboard.press('Escape');page.mouse.up();assert not calls and stored()==expected
    # Token protection and cross-item ownership are enforced by HTTP.
    response=page.request.post(base+'/api/items/'+ident+'/attachment-order',data={'order':expected,'expected_order':expected});assert response.status==403
    # Reload, compact preview, full details and image gallery follow the same order.
    page.reload();page.locator('#library-open').click();page.locator('#items [data-id="'+ident+'"]').click()
    expect(page.locator('#preview-attachments .material-card')).to_have_count(4);assert order('#preview-attachments')==expected
    page.locator('#preview-full').click();expect(page.locator('#detail-attachments .material-card')).to_have_count(4);assert order()==expected
    page.locator('#detail-attachments [data-image-view]').first.click();expect(page.locator('#image-viewer')).to_be_visible()
    first_image=next(value for value in service.item_detail(ident)['all_attachments'] if value['media'].startswith('image/'))
    expect(page.locator('#image-viewer img')).to_have_attribute('src',first_image['preview_url']);page.keyboard.press('Escape')
    assert service.archive.get(ident)['text']=='Original prose' and service.archive.get(ident)['summary']=='Preserved summary'
    assert before=={path.name:path.read_bytes() for path in (Path(root)/'files').iterdir() if path.is_file()}
    page.screenshot(path='/tmp/stellar-attachment-order.png')
    page.locator('#detail-dialog .dialog-head button').click();page.locator('#library-dialog .dialog-head button').click();page.locator('#settings-open').click();page.locator('#ui-language').select_option('en');page.locator('#settings-dialog .dialog-head button').click();page.locator('#library-open').click();page.locator('#items [data-id="'+ident+'"]').click();page.locator('#preview-full').click()
    expect(page.locator('#detail-attachments .attachment-order-hint')).to_have_text('Drag attachments to reorder. Changes are saved automatically.')
    assert not errors,errors;analyze.assert_not_called()
    print('PASS: actual cross-batch drag, arrow-key reorder, same-name identities, automatic persistence, title/note draft preservation, failure rollback, cancelled drag, token protection, preview/detail/gallery consistency, original bytes/summary preserved and bilingual controls')
   finally:browser.close()
 finally:server.shutdown();server.server_close();service.close()
