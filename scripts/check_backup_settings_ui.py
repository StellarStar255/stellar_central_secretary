import os,sys,tempfile,threading
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT))
from secretary.server import Service,handler
from secretary import library_location
from secretary.local_http import LocalHTTPServer
from playwright.sync_api import sync_playwright,expect
with tempfile.TemporaryDirectory() as temp, patch.object(library_location, 'preference_file', side_effect=lambda: Path(temp)/'settings'/'location.json'):
 service=Service(Path(temp)/'data');service.archive.configure('codex',False);service.archive.add('Original','Backup fixture')
 server=LocalHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
 try:
  with sync_playwright() as pw:
   browser=pw.chromium.launch(headless=True,executable_path=os.environ.get('CHROME_PATH') or ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' if sys.platform=='darwin' else None))
   try:
    page=browser.new_page(viewport={'width':1300,'height':1000});page.goto(base);stale=page.request.get(base+'/api/status').json()['backup'];page.locator('#settings-open').click()
    backup=(Path(temp)/'Chosen 备份').resolve();backup.mkdir()
    destination=(Path(temp)/'New Library 记忆').resolve();destination.mkdir()
    configured_backup=service.backups.folder
    with patch('secretary.directory_picker.choose',side_effect=[str(backup),None,str(destination)]) as choose:
     page.locator('#backup-folder-browse').click()
     expect(page.locator('#backup-folder')).to_have_value(str(backup))
     assert service.backups.folder==configured_backup
     with page.expect_response(lambda response:response.url.endswith('/api/directory-picker')):
      page.locator('#backup-folder-browse').click()
     expect(page.locator('#backup-folder-browse')).to_be_enabled()
     expect(page.locator('#backup-folder')).to_have_value(str(backup))
     page.evaluate('status=>StellarBackups.sync(status)',stale)
     expect(page.locator('#backup-folder')).to_have_value(str(backup))
     page.locator('#library-folder-browse').click()
     expect(page.locator('#library-folder')).to_have_value(str(destination))
     assert not library_location.read().get('target')
     assert [call.args[1] for call in choose.call_args_list]==[configured_backup,configured_backup,service.archive.root]
    page.locator('#backup-limit').fill('0.2')
    with page.expect_response(lambda response:response.url.endswith('/api/backups/configure')) as configured:page.locator('#backup-configure').click()
    result=configured.value.json();assert configured.value.ok,result
    page.evaluate('status=>StellarBackups.sync(status)',stale)
    expect(page.locator('#backup-folder')).to_have_value(str(backup/'Stellar Secretary Backups'))
    page.locator('#library-location-save').click()
    expect(page.locator('#library-location-status')).to_contain_text(str(destination))
    expect(page.locator('#data-dir')).to_contain_text(str(service.archive.root))
    assert library_location.read()['target']==str(destination)
    assert service.backups.folder==backup/'Stellar Secretary Backups'
    page.locator('#library-location-cancel').click()
    expect(page.locator('#library-location-cancel')).to_be_hidden()
    assert not library_location.read().get('target')
    page.locator('#backup-create').click();expect(page.locator('#backup-entries').get_by_role('button',name='恢复此备份',exact=True)).to_have_count(1,timeout=15000);expect(page.locator('#backup-status')).to_contain_text('0.2 GB');expect(page.locator('#backup-entries')).to_contain_text('数据库与原件已验证');page.locator('[data-backup-verify]').click();expect(page.locator('#toast')).to_contain_text('备份验证通过')
    service.backups.error='Synthetic backup failure';service.backups._save_state(state='error',last_error=service.backups.error,last_attempt='fixture')
    page.evaluate('refresh()');expect(page.locator('#settings-open')).to_have_attribute('data-backup-warning','true');expect(page.locator('#backup-error')).to_contain_text('Synthetic backup failure');assert service.backups.entries()
    print('PASS: independent folder pickers and cancellation, pending move and cancel, backup capacity settings, snapshot creation, last-success/usage display, persistent failure notice and retained previous backup')
   finally:browser.close()
 finally:server.shutdown();server.server_close();service.close()
