"""Paste/drop/pick originals directly from quick notes, with retry and no AI."""
import base64,io,os,sys,tempfile,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from PIL import Image
from playwright.sync_api import sync_playwright,expect
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary.server import Service,handler
from secretary.notes import set_note
stream=io.BytesIO();Image.new('RGB',(17,13),'#aabb33').save(stream,format='PNG')
encoded=base64.b64encode(stream.getvalue()).decode()
with tempfile.TemporaryDirectory() as root:
 service=Service(root);service.archive.configure('codex',True);ident,_=service.archive.add('Paste target','Preserved original body')
 service.archive.update(ident,summary='Preserved summary',state='ready')
 server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with patch.object(service,'queue') as queue,patch('secretary.ai.analyze_material',side_effect=AssertionError('No AI from quick notes')) as analyze,sync_playwright() as pw:
   browser=pw.chromium.launch(headless=True,**({'executable_path':os.environ.get('CHROME_PATH') or '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'} if os.environ.get('CHROME_PATH') or sys.platform=='darwin' else {}))
   try:
    page=browser.new_page(viewport={'width':1150,'height':950});errors=[];page.on('pageerror',lambda error:(errors.append(str(error)),print('PAGE ERROR:',error,flush=True)))
    base=f'http://127.0.0.1:{server.server_port}';page.goto(base);page.locator('#library-open').click();page.locator('#items [data-id="'+ident+'"]').click();page.locator('#preview-full').click()
    def paste(files,text=''):
     page.locator('#note-text').focus();page.locator('#note-text').evaluate('''(node,value)=>{const data=new DataTransfer();for(const file of value.files)data.items.add(new File([Uint8Array.from(atob(file.data),c=>c.charCodeAt(0))],file.name,{type:file.type}));if(value.text)data.setData('text/plain',value.text);node.dispatchEvent(new ClipboardEvent('paste',{clipboardData:data,bubbles:true,cancelable:true}))}''',{'files':files,'text':text})
    def file(name,data,kind='text/plain'):return {'name':name,'data':base64.b64encode(data).decode(),'type':kind}
    paste([{'name':'粘贴图片.png','data':encoded,'type':'image/png'},file('剪贴板说明.txt',b'Attachment text unique')],'速记文字 PasteMemo')
    expect(page.locator('#detail-attachments .material-card')).to_have_count(2,timeout=20000)
    expect(page.locator('#note-text')).to_have_value('速记文字 PasteMemo');expect(page.locator('#note-status')).to_have_text('已保存')
    expect(page.locator('#note-attachment-status')).to_contain_text('附件已追加到全部附件')
    assert page.locator('#note-text').evaluate('(node)=>node===document.activeElement')
    assert page.locator('#note-images img').count()==0 and not page.locator('#append-dialog').is_visible()
    assert page.evaluate('attachedFiles.length')==0
    page.locator('#detail-attachments [data-image-view]').click();expect(page.locator('#image-viewer')).to_be_visible();page.keyboard.press('Escape')
    saved=service.item_detail(ident);assert len(saved['additions'])==1 and saved['note']=='速记文字 PasteMemo'
    for entry in saved['all_attachments']:
     response=page.request.get(base+entry['download_url']);assert response.ok
     assert response.body()==(stream.getvalue() if entry['name'].endswith('.png') else b'Attachment text unique')
    # Capture all file kinds, including video. Keep notes responsive during append.
    paste([file('短片.mp4',b'FAKE-VIDEO-PRESERVED','video/mp4')]);paste([file('第二份.txt',b'SECOND')])
    expect(page.locator('#detail-attachments .material-card')).to_have_count(4,timeout=20000)
    expect(page.locator('#detail-attachments [data-video-src]')).to_have_count(1)
    # Failed append retains files for retry; text is inserted exactly once.
    page.route('**/api/items/'+ident+'/additions',lambda route:route.fulfill(status=409,content_type='application/json',body='{"error":"Synthetic temporary failure"}'))
    paste([file('重试文件.txt',b'RETRY')],' 只插入一次')
    expect(page.locator('#note-attachment-status')).to_contain_text('Synthetic temporary failure')
    expect(page.locator('#note-text')).to_have_value('速记文字 PasteMemo 只插入一次')
    assert len(service.item_detail(ident)['all_attachments'])==4
    page.unroute('**/api/items/'+ident+'/additions');page.get_by_role('button',name='重试追加',exact=True).click()
    expect(page.locator('#detail-attachments .material-card')).to_have_count(5,timeout=20000)
    expect(page.locator('#note-text')).to_have_value('速记文字 PasteMemo 只插入一次')
    # The picker and drop use the same direct-append path.
    page.locator('#note-file').set_input_files({'name':'选择的文件.txt','mimeType':'text/plain','buffer':b'PICKED'})
    expect(page.locator('#detail-attachments .material-card')).to_have_count(6,timeout=20000)
    page.evaluate('''()=>{const data=new DataTransfer();data.items.add(new File(['DROP'],'拖放.txt',{type:'text/plain'}));document.querySelector('.quick-note').dispatchEvent(new DragEvent('drop',{dataTransfer:data,bubbles:true,cancelable:true}))}''')
    expect(page.locator('#detail-attachments .material-card')).to_have_count(7,timeout=20000)
    assert page.evaluate('attachedFiles.length')==0
    held=[];pattern='**/api/items/'+ident+'/additions'
    page.route(pattern,lambda route:held.append(route))
    paste([file('编辑时追加.txt',b'KEEP-TITLE-DRAFT')])
    for _ in range(100):
     if held:break
     page.wait_for_timeout(50)
    assert held
    page.locator('#edit-title').click();page.locator('#rename-title').fill('Unsaved title draft')
    with page.expect_response(lambda response:response.url.endswith('/additions')):held[0].continue_()
    page.unroute(pattern);page.wait_for_function('(id)=>!StellarNoteAttachments.pending(id)',arg=ident)
    expect(page.locator('#rename-title')).to_have_value('Unsaved title draft')
    page.locator('#cancel-title').click();page.evaluate('refresh()')
    expect(page.locator('#detail-attachments .material-card')).to_have_count(8)
    large=b'LARGE'+b'0'*(9*1024*1024)
    page.locator('#note-file').set_input_files({'name':'大附件.bin','mimeType':'application/octet-stream','buffer':large})
    expect(page.locator('#detail-attachments .material-card')).to_have_count(9,timeout=30000)
    entry=next(file for file in service.item_detail(ident)['all_attachments'] if file['name']=='大附件.bin')
    assert page.request.get(base+entry['download_url']).body()==large
    assert not list(service.uploads.folder.iterdir())
    # Force an independent autosave exactly between the append's GET and POST.
    conflicts=[]
    def advance_note(route):
     conflicts.append(True)
     if len(conflicts)==1:
      latest=service.archive.get(ident);set_note(service.archive,ident,latest['note'],[],latest['note_version'])
     route.continue_()
    page.route('**/api/items/'+ident+'/additions',advance_note)
    paste([file('保存同时追加.txt',b'APPEND-AFTER-NOTE-AUTOSAVE')])
    expect(page.locator('#detail-attachments .material-card')).to_have_count(10,timeout=20000)
    assert len(conflicts)==2,'Only the known revision conflict should be retried'
    page.unroute('**/api/items/'+ident+'/additions')
    assert page.locator('#note-text').evaluate("node=>{const data=new DataTransfer();data.setData('text/plain','plain text');const event=new ClipboardEvent('paste',{clipboardData:data,bubbles:true,cancelable:true});node.dispatchEvent(event);return !event.defaultPrevented}")
    page.reload();page.locator('#library-open').click();page.locator('#items [data-id="'+ident+'"]').click();page.locator('#preview-full').click()
    expect(page.locator('#detail-attachments .material-card')).to_have_count(10)
    expect(page.locator('#note-text')).to_have_value('速记文字 PasteMemo 只插入一次')
    item=service.archive.get(ident);assert item['text']=='Preserved original body' and item['summary']=='Preserved summary' and not item['note_images']
    page.locator('#detail-dialog .dialog-head button').click();page.locator('#library-dialog .dialog-head button').click();page.locator('#settings-open').click();page.locator('#ui-language').select_option('en');page.locator('#settings-dialog .dialog-head button').click();page.locator('#library-open').click();page.locator('#items [data-id="'+ident+'"]').click();page.locator('#preview-full').click()
    expect(page.locator('#note-add-image')).to_have_text('+ Add attachments');assert not errors,errors;queue.assert_not_called();analyze.assert_not_called()
    print('PASS: quick-note mixed clipboard files/text, image/video/file originals in top catalogue, direct pick/drop, serial appends, visible feedback, focus/text preservation, retry without duplicate text, persisted originals and summary, bilingual controls and zero model calls')
   finally:browser.close()
 finally:server.shutdown();server.server_close();service.close()
