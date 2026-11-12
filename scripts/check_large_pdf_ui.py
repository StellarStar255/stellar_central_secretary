"""51 MB PDF upload: first five pages, real thumbnail/ranges, bounded mocked summary."""
import os,sys,tempfile,threading
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent.parent;sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_large_pdf_preview import fixture
from secretary.server import Service,handler
from secretary.local_http import LocalHTTPServer
from playwright.sync_api import sync_playwright,expect

with tempfile.TemporaryDirectory() as temp:
 source=Path(temp)/'large.pdf';fixture(source,padding=51*1024*1024)
 service=Service(Path(temp)/'archive');service.archive.configure('codex',False);service.archive.set_language('en')
 server=LocalHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
 calls=[]
 def summarize(text,title,backend,images,scope):
  assert 'PAGETOKEN5' in text and 'PAGETOKEN6' not in text and '大 PDF' in scope and not images
  calls.append(text);return {'title':title,'summary':scope+'\n\nSynthetic front-page summary.','tags':['PDF'],'category':'Synthetic','state':'ready','error':''},''
 try:
  with patch('secretary.ai.analyze_material',side_effect=summarize),sync_playwright() as pw:
   browser=pw.chromium.launch(headless=True,executable_path=os.environ.get('CHROME_PATH') or ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' if sys.platform=='darwin' else None))
   try:
    page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];page.on('pageerror',lambda error:errors.append(str(error)));page.goto(base)
    page.wait_for_function('historyLoaded === true')
    page.locator('#archive-only').check();page.locator('#file-input').set_input_files(source)
    with page.expect_response(lambda response:response.url.endswith('/api/ingest'),timeout=30000) as saved:page.locator('#send-button').click()
    result=saved.value.json();assert saved.value.ok,result;item=result['item'];ident=item['id']
    assert 'PAGETOKEN5' in item['text'] and 'PAGETOKEN6' not in item['text'] and not calls
    page.locator('#library-open').click();page.locator('#items [data-id="'+ident+'"]').click();card=page.locator('#preview-attachments .material-card')
    expect(card).to_have_count(1);expect(card.locator('.warning')).to_contain_text('first 5 pages')
    file=item['all_attachments'][0];response=page.request.get(base+file['thumbnail_url']);assert response.ok and response.headers['content-type']=='image/png'
    for suffix,expected in [('bytes=0-4',b'%PDF-'),('bytes=-6',b'%%EOF\n')]:
     response=page.request.get(base+file['preview_url'],headers={'Range':suffix});assert response.status==206 and response.body()==expected
    page.locator('#preview-full').click();page.locator('#retry-ai').click()
    expect(page.locator('#detail-content')).to_contain_text('Synthetic front-page summary.',timeout=15000)
    assert len(calls)==1;assert service.archive.list(q='PAGETOKEN5') and not service.archive.list(q='PAGETOKEN6')
    assert not errors,errors
    print('PASS: real 51 MB chunked PDF upload, readable first-five-page preview and thumbnail, original range reads, explicit partial-summary scope, no sixth-page/model cloud access')
   finally:browser.close()
 finally:server.shutdown();server.server_close();service.close()
