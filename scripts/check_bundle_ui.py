"""Synthetic pasted image + text + file in one archived question, no cloud calls."""
import base64,io,json,os,sys,tempfile,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from PIL import Image
from secretary.server import Service,handler
from secretary import ai
from playwright.sync_api import sync_playwright,expect

stream=io.BytesIO();Image.new('RGB',(50,40),'orange').save(stream,format='PNG');png=stream.getvalue()
with tempfile.TemporaryDirectory() as temp:
 service=Service(temp);service.archive.configure('codex',False)
 other,_=service.archive.add('Unrelated','UNRELATED_SECRET_SHOULD_NOT_BE_SENT')
 before=service.archive.get(other)
 server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
 def model(prompt,backend,**options):
  assert 'UNRELATED_SECRET_SHOULD_NOT_BE_SENT' not in prompt
  assert 'Attached synthetic context' in prompt and len(options['images'])==1
  return json.dumps({'title':'Grouped example','summary':'Combined image and file summary','category':'Examples','tags':['Combined'],'vision_text':'DemoVisionOrange is visible in the image.','answer':'Synthetic combined answer [1]'})
 try:
  with patch.object(ai,'run',side_effect=model) as mocked,sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path=os.environ.get('CHROME_PATH','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),headless=True)
   try:
    page=browser.new_page(viewport={'width':1280,'height':950});errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto(base);expect(page.locator('#model-label')).to_have_text('ChatGPT · Codex')
    page.locator('#message-input').fill('Question: ')
    page.locator('#message-input').evaluate('(input)=>input.setSelectionRange(input.value.length,input.value.length)')
    pasted=page.evaluate('''data=>{const transfer=new DataTransfer();transfer.items.add(new File([Uint8Array.from(atob(data),c=>c.charCodeAt(0))],'pasted.png',{type:'image/png'}));transfer.setData('text/plain','Explain this picture and the attached context.');const event=new ClipboardEvent('paste',{clipboardData:transfer,bubbles:true,cancelable:true});document.querySelector('#message-input').dispatchEvent(event);return event.defaultPrevented}''',base64.b64encode(png).decode())
    assert pasted;expect(page.locator('#attachments img')).to_be_visible()
    assert page.locator('#message-input').input_value().startswith('Question: Explain')
    page.locator('#file-input').set_input_files({'name':'context.txt','mimeType':'text/plain','buffer':b'Attached synthetic context and decisions.'})
    expect(page.locator('#attachments .attachment')).to_have_count(2);page.locator('#send-button').click()
    expect(page.locator('#messages')).to_contain_text('Synthetic combined answer')
    assert mocked.call_count==1 and len(service.archive.list())==2
    grouped=next(item for item in service.archive.list() if item['id']!=other)
    expect(page.locator('.message.user .message-images img')).to_be_visible()
    page.locator('#messages .archive-card[data-id="'+grouped['id']+'"]').click()
    expect(page.locator('.bundle-file')).to_have_count(2);expect(page.locator('.bundle-file img')).to_be_visible()
    expect(page.get_by_role('heading',name='图片解读（AI 生成，请核对原图）')).to_be_visible()
    assert 'Question: Explain' in service.archive.get(grouped['id'])['text']
    image=service.item_detail(grouped['id'])['attachments'][0]
    response=page.request.get(base+'/api/items/'+grouped['id']+'/attachments/'+image['id']+'/preview')
    assert response.body()==png and response.headers['content-type']=='image/png'
    page.screenshot(path='/tmp/secretary-grouped-material.png')
    page.locator('#detail-dialog .dialog-head button').click();page.reload()
    expect(page.locator('.message.user .message-images img')).to_be_visible()
    page.locator('#recent-items [data-id="'+grouped['id']+'"]').click(button='right');page.locator('#archive-delete-menu').click();page.locator('#delete-archive-confirm').click()
    expect(page.locator('#toast')).to_have_text('归档已删除');expect(page.locator('.message-images img')).to_have_count(0)
    assert service.archive.get(other)==before and len(service.archive.list())==1 and not errors,errors
    # Annotation-only groups respect disabled automatic AI; no implicit question.
    page.locator('#message-input').fill('My field notes from today')
    page.locator('#file-input').set_input_files([{'name':'pasted.png','mimeType':'image/png','buffer':png},{'name':'context.txt','mimeType':'text/plain','buffer':b'Attached synthetic context'}])
    page.locator('#send-button').click();expect(page.locator('#messages .archive-card')).to_have_count(1)
    assert len(service.archive.list())==2 and mocked.call_count==1
    print('PASS: pasted PNG and clipboard text preserved; additional file submitted as one archive; one scoped model call; native image payload; originals preview; AI vision label; persisted image bubble; grouped deletion; unrelated source preserved; no cloud calls')
   finally:browser.close()
 finally:service.close();server.shutdown();server.server_close()
