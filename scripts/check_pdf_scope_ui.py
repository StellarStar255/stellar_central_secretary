"""Coverage shown beside preview/summary follows the actual incremental input."""
import os,sys,tempfile,threading,json
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent.parent;sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_large_pdf_preview import fixture
from secretary.server import Service,handler
from secretary.local_http import LocalHTTPServer
from secretary import pdf_reading
from playwright.sync_api import sync_playwright,expect
with tempfile.TemporaryDirectory() as temp:
 source=Path(temp)/'pages.pdf';fixture(source,pages=9);service=Service(Path(temp)/'data');service.archive.configure('codex',False)
 ident,_=service.archive.add(text='original description',filename='pages.pdf',data=source.read_bytes())
 pdf_reading.read(service.archive,ident,None,None,{'start':1,'end':2})
 with patch('secretary.ai.run',return_value=json.dumps({'summary':'First retained summary','tags':[]})):service.process(ident)
 pdf_reading.read(service.archive,ident,None,None,{'start':6,'end':7});prompts=[]
 server=LocalHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
 try:
  with sync_playwright() as pw:
   browser=pw.chromium.launch(headless=True,executable_path=os.environ.get('CHROME_PATH') or ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' if sys.platform=='darwin' else None))
   try:
    page=browser.new_page(viewport={'width':1400,'height':1000});page.goto(base);page.locator('#library-open').click();page.locator('#items [data-id="'+ident+'"]').click();panel=page.locator('#preview-pdf-coverage');expect(panel).to_contain_text('1–2');expect(panel).to_contain_text('6–7')
    def model(prompt,*args,**kwargs):prompts.append(prompt);return json.dumps({'summary':'New pages summary','tags':[]})
    with patch('secretary.ai.run',side_effect=model):panel.locator('[data-pdf-summary]').click();expect(panel).not_to_contain_text('待总结：',timeout=15000)
    assert len(prompts)==1 and 'PAGETOKEN6' in prompts[0] and 'PAGETOKEN1' not in prompts[0];assert 'First retained summary' in service.archive.get(ident)['summary'];expect(panel).to_contain_text('1–2, 6–7')
    print('PASS: exact coverage in preview, one incremental model call, old summary retained, only new page text submitted')
   finally:browser.close()
 finally:server.shutdown();server.server_close();service.close()
