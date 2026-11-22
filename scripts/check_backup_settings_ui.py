import os,sys,tempfile,threading
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT))
from secretary.server import Service,handler
from secretary import browser_reader,library_location
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
    page.locator('#capture-proxy-mode').select_option('direct')
    with patch.object(browser_reader,'test_chatgpt_connection',return_value={'mode':'direct','route':'direct','stage':'blocked','status':403}) as probe:
     page.locator('#capture-connection-test').click()
     expect(page.locator('#capture-connection-result')).to_contain_text('直连 · 已连接到网站')
     expect(page.locator('#capture-connection-result')).to_contain_text('HTTP 403')
     probe.assert_called_once_with({'mode':'direct','url':''},None)
    page.locator('#ui-language').select_option('en')
    expect(page.locator('#capture-connection-test')).to_have_text('Test ChatGPT connection')
    expect(page.locator('#backup-create')).to_have_text('Back up and verify now')
    page.locator('#ui-language').select_option('zh')
    backup=(Path(temp)/'Chosen 备份').resolve();backup.mkdir()
    destination=(Path(temp)/'New Library 记忆').resolve();destination.mkdir()
    configured_backup=service.backups.folder
    old_snapshot=service.backups.create()
    existing=destination/'existing'
    existing.touch()
    with patch('secretary.directory_picker.choose',side_effect=[str(backup),None,str(destination)]) as choose:
     page.locator('#backup-folder-browse').click()
     expect(page.locator('#backup-folder')).to_have_value(str(backup))
     expect(page.locator('#backup-create')).to_be_disabled()
     assert service.backups.folder==configured_backup
     with page.expect_response(lambda response:response.url.endswith('/api/directory-picker')):
      page.locator('#backup-folder-browse').click()
     expect(page.locator('#backup-folder-browse')).to_be_enabled()
     expect(page.locator('#backup-folder')).to_have_value(str(backup))
     page.evaluate('status=>StellarBackups.sync(status)',stale)
     expect(page.locator('#backup-folder')).to_have_value(str(backup))
     page.locator('#library-folder-browse').click()
     expect(page.locator('#library-folder')).to_have_value(str(destination))
     expect(page.locator('#library-location-preflight')).to_contain_text('目标文件夹非空')
     expect(page.locator('#library-location-save')).to_be_disabled()
     assert not library_location.read().get('target')
     assert [call.args[1] for call in choose.call_args_list]==[configured_backup,configured_backup,service.archive.root]
    existing.unlink()
    page.locator('#library-folder').fill('')
    page.locator('#library-folder').fill(str(destination))
    expect(page.locator('#library-location-preflight')).to_contain_text('预计迁移大小')
    expect(page.locator('#library-location-preflight')).to_contain_text('目标磁盘可用')
    expect(page.locator('#library-location-preflight')).to_contain_text('目标文件夹为空')
    expect(page.locator('#library-location-preflight')).to_contain_text('目标文件夹可写')
    page.locator('#backup-limit').fill('0.2')
    with page.expect_response(lambda response:response.url.endswith('/api/backups/configure')) as configured:page.locator('#backup-configure').click()
    result=configured.value.json();assert configured.value.ok,result
    with page.expect_response(lambda response:response.url.endswith('/api/backups/create')):
     response=page.evaluate("folder=>api('/api/backups/create',{folder}).catch(error=>error.message)",str(configured_backup))
    assert '备份目录已更改' in response
    page.evaluate('status=>StellarBackups.sync(status)',stale)
    expect(page.locator('#backup-folder')).to_have_value(str(backup/'Stellar Secretary Backups'))
    expect(page.locator('#backup-create-result')).to_contain_text('已保存备份目录')
    page.locator('#library-location-save').click()
    expect(page.locator('#library-location-status')).to_contain_text(str(destination))
    expect(page.locator('#data-dir')).to_contain_text(str(service.archive.root))
    assert library_location.read()['target']==str(destination)
    assert service.backups.folder==backup/'Stellar Secretary Backups'
    page.locator('#library-location-cancel').click()
    expect(page.locator('#library-location-cancel')).to_be_hidden()
    assert not library_location.read().get('target')
    page.locator('#backup-create').click()
    expect(page.locator('#backup-create-result')).to_contain_text('备份已写入并通过验证：'+str(service.backups.folder))
    expect(page.locator('#backup-entries').get_by_role('button',name='恢复此备份',exact=True)).to_have_count(2,timeout=15000)
    expect(page.locator('#backup-status')).to_contain_text('0.2 GB')
    expect(page.locator('#backup-entries')).to_contain_text('数据库与原件已验证')
    snapshot=next(entry for entry in service.backups.entries() if entry['folder']==str(service.backups.folder))
    assert snapshot['verification']['state']=='verified'
    assert (service.backups.folder/(snapshot['id']+'.zip')).is_file()
    assert (configured_backup/(old_snapshot['id']+'.zip')).is_file()
    page.locator('[data-backup-verify="'+snapshot['id']+'"]').click()
    expect(page.locator('#toast')).to_contain_text('备份验证通过')
    service.backups.error='Synthetic backup failure';service.backups._save_state(state='error',last_error=service.backups.error,last_attempt='fixture')
    page.evaluate('refresh()');expect(page.locator('#settings-open')).to_have_attribute('data-backup-warning','true');expect(page.locator('#backup-error')).to_contain_text('Synthetic backup failure');assert service.backups.entries()
    print('PASS: capture probe and English controls, migration preflight and cancellation, verified snapshot in the new backup folder, previous snapshot retained')
   finally:browser.close()
 finally:server.shutdown();server.server_close();service.close()
