"""Unified original/additional attachments, local thumbnails and quick open."""
import base64,io,os,sys,tempfile,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'tests'))
from PIL import Image
from pdf_fixture import pdf_bytes
from secretary.server import Service,handler
from playwright.sync_api import sync_playwright,expect

def picture(size,color):
    output=io.BytesIO();Image.new('RGB',size,color).save(output,format='PNG');return output.getvalue()
def file(name,data):return {'name':name,'data':base64.b64encode(data).decode()}
with tempfile.TemporaryDirectory() as root:
    service=Service(root);service.archive.configure('codex',False)
    original=picture((1600,800),'blue');extra=picture((900,600),'orange')
    item=service.ingest({'text':'Synthetic attachment overview','attachments':[file('diagram.png',original),file('report.pdf',pdf_bytes()),file('broken.pdf',b'invalid PDF'),file('readme.txt',b'Synthetic reference')],'archive_only':True})['item']
    item=service.append_material(item['id'],{'text':'Supplemental evidence','attachments':[file('diagram.png',extra)],'expected_updated':item['updated'],'summarize':False})['item'];ident=item['id'];before=service.archive.get(ident)
    server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
    try:
        with patch('secretary.ai.run') as model,patch('secretary.attachment_editor.launch') as launch,sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,executable_path=os.environ.get('CHROME_PATH') or ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' if sys.platform=='darwin' else None))
            try:
                page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(base);expect(page.locator('#model-label')).to_have_text('ChatGPT · Codex',timeout=15000)
                page.locator('#library-open').click();page.locator('#items [data-id="'+ident+'"]').click()
                cards=page.locator('#preview-attachments .material-card');expect(cards).to_have_count(5)
                metadata=page.request.get(base+'/api/items/'+ident+'/quick-preview').json()['all_attachments'];assert len(metadata)==5 and sum(bool(f['batch_id']) for f in metadata)==1
                for entry in metadata:
                    response=page.request.get(base+entry['thumbnail_url']);assert response.ok
                    if entry['name'] in ('diagram.png','report.pdf'):
                        assert response.headers['content-type']=='image/png'
                        with Image.open(io.BytesIO(response.body())) as thumbnail:assert max(thumbnail.size)<=320
                    else:assert response.headers['content-type']=='image/svg+xml'
                assert cards.first.bounding_box()['y']<page.locator('#preview-summary-heading').bounding_box()['y']
                cards.filter(has=page.locator('[data-image-view]')).first.locator('[data-image-view]').click();page.wait_for_function('()=>document.querySelector("#image-viewer img").naturalWidth===1600');page.keyboard.press('ArrowRight');page.wait_for_function('()=>document.querySelector("#image-viewer img").naturalWidth===900');page.keyboard.press('Escape');expect(page.locator('#library-dialog')).to_be_visible();expect(page.locator('#detail-dialog')).not_to_be_visible()
                pdf_url=base+next(entry['preview_url'] for entry in metadata if entry['name']=='report.pdf')
                response=page.request.get(pdf_url);assert response.ok and response.headers['content-type']=='application/pdf' and response.body()==pdf_bytes()
                # Chrome may replace the URL with its internal PDF viewer on Windows.
                with page.context.expect_event('request',predicate=lambda request:request.url==pdf_url) as requested,page.expect_popup() as opened:
                    cards.filter(has_text='report.pdf').locator('.material-thumb').click()
                assert requested.value.method=='GET';opened.value.close()
                page.screenshot(path='/tmp/secretary-attachment-overview-preview.png')
                page.locator('#preview-full').click();expect(page.locator('#detail-attachments .material-card')).to_have_count(5)
                section=page.locator('#detail-attachments');assert section.bounding_box()['y']<page.locator('.quick-note').bounding_box()['y']
                expect(page.locator('.addition-batch')).to_have_count(1);expect(page.locator('.addition-batch .material-card')).to_have_count(0)
                page.locator('#detail-attachments .material-card[data-batch="'+metadata[-1]['batch_id']+'"] [data-image-view]').click();page.wait_for_function('()=>document.querySelector("#image-viewer img").naturalWidth===900');page.keyboard.press('Escape')
                page.screenshot(path='/tmp/secretary-attachment-overview-details.png')
                assert not errors and not launch.called and not model.called,errors
                for key in ('title','text','summary','note','note_images','additions'):assert service.archive.get(ident)[key]==before[key],key
                # Trashed sources cannot be read from the thumbnail cache.
                service.trash_item(ident,service.archive.get(ident)['updated']);assert page.request.get(base+metadata[0]['thumbnail_url']).status==404
                print('PASS: original and added attachments in one top section and library preview, PDF/image thumbnails, damaged-file type card, full-resolution gallery across batches, PDF quick open, history retained, no model/external image call, no source changes, trashed thumbnail rejected')
            finally:browser.close()
    finally:server.shutdown();server.server_close();service.close()
