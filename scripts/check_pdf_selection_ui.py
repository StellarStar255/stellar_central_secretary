"""Real on-device PDF range reading/continuation and page display with no model call."""
import os,sys,tempfile,threading
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent.parent;sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_large_pdf_preview import fixture
from secretary.server import Service,handler
from secretary.local_http import LocalHTTPServer
from secretary import bundles
from playwright.sync_api import sync_playwright,expect
with tempfile.TemporaryDirectory() as temp:
 source=Path(temp)/'pages.pdf';fixture(source,pages=9)
 service=Service(Path(temp)/'data');service.archive.configure('codex',False)
 data,text=bundles.create('',[{'name':'pages.pdf','source':source}]);ident,_=service.archive.add(text=text,filename='materials.stellar.zip',data=data);bundles.cleanup(data)
 server=LocalHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
 try:
  with patch('secretary.ai.run',side_effect=AssertionError('Unexpected cloud call')),sync_playwright() as pw:
   browser=pw.chromium.launch(headless=True,executable_path=os.environ.get('CHROME_PATH') or ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' if sys.platform=='darwin' else None))
   try:
    page=browser.new_page(viewport={'width':1400,'height':1000});errors=[];page.on('pageerror',lambda error:errors.append(str(error)));page.goto(base)
    page.locator('#library-open').click();page.locator('#items [data-id="'+ident+'"]').click();page.locator('[data-pdf-read]').click()
    expect(page.locator('[data-pdf-scope]')).to_contain_text('1, 2, 3, 4, 5');expect(page.locator('[data-pdf-text]')).to_contain_text('PAGETOKEN1')
    page.locator('[data-pdf-next]').click();expect(page.locator('[data-pdf-text]')).to_contain_text('PAGETOKEN6')
    expect(page.locator('[data-pdf-scope]')).to_contain_text('6, 7, 8, 9');assert page.locator('[data-pdf-original]').get_attribute('href').endswith('#page=6')
    page.locator('[data-pdf-close]').click();assert service.archive.list(q='PAGETOKEN9');page.locator('#search').fill('PAGETOKEN9');hit=page.locator('[data-origin-item]').filter(has_text='p.9').first;hit.click();expect(page.locator('[data-pdf-text]')).to_contain_text('PAGETOKEN9');page.locator('[data-pdf-close]').click();page.locator('#library-dialog .dialog-head button').click()
    with patch('secretary.ai.run',return_value='Synthetic answer [1]'):
     page.locator('#input-mode').select_option('ask');page.locator('#message-input').fill('PAGETOKEN9?');page.locator('#send-button').click();source=page.locator('.source-list .source').first;expect(source).to_contain_text('p.9');source.click();expect(page.locator('[data-pdf-text]')).to_contain_text('PAGETOKEN9')
    assert not errors,errors
    print('PASS: PDF range controls, continuation to pages 6-9, local page image/text, searchable retained selections, zero model calls')
   finally:browser.close()
 finally:server.shutdown();server.server_close();service.close()
