"""Storage cleanup requires an explicit selection and keeps active/original files."""
import os,re,sys,tempfile,threading,time,json
from pathlib import Path
from shutil import copyfile
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT))
from secretary.server import Service,handler
from secretary.local_http import LocalHTTPServer
from playwright.sync_api import sync_playwright,expect

class StorageTestServer(LocalHTTPServer):
 request_queue_size=32

with tempfile.TemporaryDirectory() as temp:
 service=Service(Path(temp)/'data');ident,_=service.archive.add('Keep','original',filename='keep.txt',data=b'KEEP')
 expired=[service.uploads.start(name,10) for name in ('expired-one.bin','expired-two.bin')]
 active=service.uploads.start('active.bin',10)
 for upload in expired:
  meta=service.uploads.path(upload['id']).with_suffix('.json');value=json.loads(meta.read_text());value['updated']=time.time()-90000;meta.write_text(json.dumps(value))
 server=StorageTestServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with sync_playwright() as pw:
   browser=pw.chromium.launch(headless=True,executable_path=os.environ.get('CHROME_PATH') or ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' if sys.platform=='darwin' else None))
   try:
    page=browser.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)));page.goto(f'http://127.0.0.1:{server.server_port}');page.locator('#settings-open').click()
    page.locator('#ui-language').select_option('en')
    expect(page.locator('#settings-title')).to_have_text('Models & settings')
    page.locator('#storage-open').click()
    boxes=page.locator('[data-storage-id]')
    selected=page.locator('[data-storage-id]:checked')
    toggle=page.locator('[data-storage-select-all]')
    clean=page.locator('[data-storage-clean]')
    expect(page.locator('[data-storage-overview]')).to_contain_text('Original files')
    expect(boxes).to_have_count(2)
    expect(selected).to_have_count(0)
    expect(clean).to_be_disabled()
    boxes.first.check()
    expect(toggle).to_have_text('Select all')
    toggle.click()
    expect(selected).to_have_count(2)
    expect(toggle).to_have_text('Deselect all')
    expect(clean).to_be_enabled()
    toggle.click()
    expect(selected).to_have_count(0)
    expect(clean).to_be_disabled()
    toggle.click()
    page.locator('[data-storage-refresh]').click()
    expect(boxes).to_have_count(2)
    expect(selected).to_have_count(0)
    toggle.click()
    confirmation=page.get_by_role('dialog',name='Confirm cleanup')
    clean.click()
    expect(confirmation).to_be_visible()
    expect(confirmation).to_contain_text('Selected entries: 2')
    expect(confirmation.get_by_role('button',name='Cancel')).to_be_focused()
    assert all(service.uploads.path(upload['id']).exists() for upload in expired)
    page.keyboard.press('Escape')
    expect(confirmation).to_be_hidden()
    expect(selected).to_have_count(2)
    clean.click()
    confirmation.get_by_role('button',name='Cancel').click()
    expect(confirmation).to_be_hidden()
    assert all(service.uploads.path(upload['id']).exists() for upload in expired)
    clean.click()
    confirmation.get_by_role('button',name='Confirm cleanup').click()
    expect(page.locator('[data-storage-result]')).to_have_text('Removed entries: 2')
    expect(page.locator('[data-storage-status]')).to_contain_text('no eligible expired uploads')
    expect(boxes).to_have_count(0)
    expect(toggle).to_be_hidden()
    assert not any(service.uploads.path(upload['id']).exists() for upload in expired)
    assert service.uploads.path(active['id']).exists()
    assert (service.archive.root/'files'/ident).read_bytes()==b'KEEP'
    backups=service.backups
    old=backups.folder
    snapshot=backups.create()
    backups.create()
    backups.configure({'folder':str(Path(temp)/'shared')})
    for ext in ('.zip','.json'):
     filename=snapshot['id']+ext
     copyfile(old/filename,backups.folder/filename)
    backups.create()
    backups.create()  # Also expose a non-duplicate candidate.
    page.locator('[data-storage-refresh]').click()
    expect(boxes).to_have_count(3)
    locations=page.locator('.cleanup-backup-location')
    expect(locations).to_have_count(2)
    for title,folder in [('Current backup folder',backups.folder),('Previous backup folder',old)]:
     location=locations.filter(has_text=title)
     location.locator('summary').click()
     expect(location.locator('span')).to_have_text(str(folder))
     expect(location.locator('span')).to_be_visible()
    expect(selected).to_have_count(0)
    page.get_by_role('checkbox',name=re.compile('Previous backup folder')).check()
    clean.click()
    confirmation.get_by_role('button',name='Confirm cleanup').click()
    expect(page.locator('[data-storage-result]')).to_have_text('Removed entries: 1')
    expect(locations).to_have_count(0)
    assert not (old/(snapshot['id']+'.zip')).exists()
    service.archive.update(ident,title='changed')
    backups.restore(snapshot['id'],folder=str(backups.folder))
    assert service.archive.get(ident)['title']=='Keep'
    assert not errors,errors
    print('PASS: select/deselect all, reset on scan, cancel and confirm, duplicate folder selection, restore of retained copy, active uploads and originals preserved')
   finally:browser.close()
 finally:server.shutdown();server.server_close();service.close()
