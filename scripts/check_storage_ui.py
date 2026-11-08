"""Storage cleanup requires an explicit selection and keeps active/original files."""
import os,sys,tempfile,threading,time,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT))
from secretary.server import Service,handler
from secretary.local_http import LocalHTTPServer
from playwright.sync_api import sync_playwright,expect
with tempfile.TemporaryDirectory() as temp:
 service=Service(Path(temp)/'data');ident,_=service.archive.add('Keep','original',filename='keep.txt',data=b'KEEP')
 upload=service.uploads.start('expired.bin',10);meta=service.uploads.path(upload['id']).with_suffix('.json');value=json.loads(meta.read_text());value['updated']=time.time()-90000;meta.write_text(json.dumps(value))
 server=LocalHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with sync_playwright() as pw:
   browser=pw.chromium.launch(headless=True,executable_path=os.environ.get('CHROME_PATH') or ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' if sys.platform=='darwin' else None))
   try:
    page=browser.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)));page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#settings-open').click();page.locator('#storage-open').click()
    expect(page.locator('[data-storage-overview]')).to_contain_text('原件');expect(page.locator('[data-storage-id]')).to_have_count(1);expect(page.locator('[data-storage-clean]')).to_be_disabled();page.locator('[data-storage-id]').check();expect(page.locator('[data-storage-clean]')).to_be_enabled()
    page.once('dialog',lambda dialog:dialog.dismiss());page.locator('[data-storage-clean]').click();assert service.uploads.path(upload['id']).exists()
    page.once('dialog',lambda dialog:dialog.accept());page.locator('[data-storage-clean]').click();expect(page.locator('[data-storage-items] label')).to_have_count(0);assert not service.uploads.path(upload['id']).exists();assert (service.archive.root/'files'/ident).read_bytes()==b'KEEP';assert not errors,errors
    print('PASS: storage accounting, no default selection, confirmation cancel preserves files, selected expiry cleaned and original preserved')
   finally:browser.close()
 finally:server.shutdown();server.server_close();service.close()
