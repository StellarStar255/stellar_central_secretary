import os,sys,tempfile,threading
from zipfile import ZipFile
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT))
from secretary.server import Service,handler
from secretary import browser_reader,library_location
from secretary.local_http import LocalHTTPServer
from playwright.sync_api import sync_playwright,expect

class BackupTestServer(LocalHTTPServer):
 request_queue_size=32

with tempfile.TemporaryDirectory() as temp, patch.object(library_location, 'preference_file', side_effect=lambda: Path(temp)/'settings'/'location.json'):
 service=Service(Path(temp)/'data');service.archive.configure('codex',False);service.archive.add('Original','Backup fixture')
 server=BackupTestServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
 try:
  with sync_playwright() as pw:
   browser=pw.chromium.launch(headless=True,executable_path=os.environ.get('CHROME_PATH') or ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' if sys.platform=='darwin' else None))
   try:
    page=browser.new_page(viewport={'width':1300,'height':1000})
    page.on('pageerror',lambda error:print('PAGE ERROR:',error,flush=True))
    page.goto(base);stale=page.request.get(base+'/api/status').json()['backup'];page.locator('#settings-open').click()
    expect(page.locator('#backup-error')).to_be_hidden()
    page.locator('#capture-proxy-mode').select_option('direct')
    with patch.object(browser_reader,'test_chatgpt_connection',return_value={'mode':'direct','route':'direct','stage':'blocked','status':403}) as probe:
     page.locator('#capture-connection-test').click()
     expect(page.locator('#capture-connection-result')).to_contain_text('直连 · 已连接到网站')
     expect(page.locator('#capture-connection-result')).to_contain_text('HTTP 403')
     probe.assert_called_once_with({'mode':'direct','url':''},None)
    page.locator('#ui-language').select_option('en')
    expect(page.locator('#capture-connection-test')).to_have_text('Test ChatGPT connection')
    expect(page.locator('#backup-create')).to_have_text('Back up and verify now')
    expect(page.locator('#library-location-change')).to_have_text('Browse…')
    download=page.locator('#backup-download')
    expect(download).to_have_text('Download full backup')
    expect(download).to_have_attribute('title','Download a full backup with originals, database, and JSON')
    expect(page.locator('#data-dir')).to_have_attribute('readonly','')
    expect(page.locator('#data-dir')).to_have_attribute('title',str(service.archive.root))
    for width in (1300, 390):
     page.set_viewport_size({'width':width,'height':1000})
     for selector in ('.directory-field-with-open','.backup-actions'):
      assert page.locator(selector).evaluate_all('rows=>rows.every(row=>row.scrollWidth<=row.clientWidth)')
     for button in ('#library-location-change','#backup-folder-browse'):
      assert page.locator(button).evaluate('(el,narrow)=>{const row=el.parentElement;const path=row.firstElementChild.getBoundingClientRect();return narrow?el.getBoundingClientRect().top>path.bottom:el.getBoundingClientRect().top===path.top}',width<520)
    page.set_viewport_size({'width':1300,'height':1000})
    assert download.evaluate("link=>link.getBoundingClientRect().left>document.querySelector('#storage-open').getBoundingClientRect().right")
    page.locator('#ui-language').select_option('zh')
    expect(page.locator('#data-dir')).to_have_value(str(service.archive.root))
    expect(download).to_have_text('下载完整备份')
    expect(page.locator('#library-location-restart')).to_be_hidden()
    expect(page.locator('#library-location-change')).to_have_attribute('aria-expanded','false')
    expect(page.locator('#library-location-editor')).to_be_hidden()
    expect(page.locator('#library-location-save')).to_be_hidden()
    backup=(Path(temp)/'Chosen 备份').resolve();backup.mkdir()
    destination=(Path(temp)/'New Library 记忆').resolve();destination.mkdir()
    configured_backup=service.backups.folder
    old_snapshot=service.backups.create()
    with patch('secretary.attachment_editor.launch') as launch:
     for purpose in ('library','backup'):
      with page.expect_response(lambda response:response.url.endswith('/api/data-directory/open')) as opened:
       page.locator('#'+purpose+'-folder-open').click()
      assert opened.value.ok
     assert [call.args[0] for call in launch.call_args_list]==[service.archive.root,configured_backup]
    existing=destination/'existing'
    existing.touch()
    with patch('secretary.directory_picker.choose',side_effect=[str(backup),None,None,str(destination)]) as choose:
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
     with page.expect_response(lambda response:response.url.endswith('/api/directory-picker')):
      page.locator('#library-location-change').click()
     expect(page.locator('#library-location-editor')).to_be_visible()
     expect(page.locator('#library-location-change')).to_have_attribute('aria-expanded','true')
     expect(page.locator('#library-location-save')).to_be_hidden()
     page.locator('#library-location-discard').click()
     expect(page.locator('#library-location-editor')).to_be_hidden()
     page.locator('#library-location-change').click()
     expect(page.locator('#library-folder')).to_have_value(str(destination))
     expect(page.locator('#library-location-preflight')).to_contain_text('目标文件夹非空')
     expect(page.locator('#library-location-save')).to_be_disabled()
     assert not library_location.read().get('target')
     assert [call.args[1] for call in choose.call_args_list]==[configured_backup,configured_backup,service.archive.root,service.archive.root]
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
    expect(page.locator('#backup-status')).to_contain_text('此目录尚无备份')
    expect(page.locator('#backup-status')).not_to_contain_text('最近验证通过')
    expect(page.locator('#backup-create-result')).to_contain_text('已保存备份目录')
    page.locator('#library-location-save').click()
    expect(page.locator('#library-location-status')).to_contain_text(str(destination))
    expect(page.locator('#library-location-restart')).to_be_visible()
    expect(page.locator('#library-location-editor')).to_be_hidden()
    expect(page.locator('#data-dir')).to_have_value(str(service.archive.root))
    assert library_location.read()['target']==str(destination)
    service.restart_supported=True
    with patch.object(service,'runtime',return_value={'processing':1,'reading':0,'answering':0}):
     page.locator('#library-location-restart').click()
     expect(page.locator('#library-restart-status')).to_contain_text('请等待当前任务')
    assert not service.restart_requested
    assert service.backups.folder==backup/'Stellar Secretary Backups'
    page.locator('#library-location-cancel').click()
    expect(page.locator('#library-location-cancel')).to_be_hidden()
    expect(page.locator('#library-location-status')).to_be_empty()
    assert not library_location.read().get('target')
    page.locator('#backup-create').click()
    expect(page.locator('#backup-create-result')).to_contain_text('备份已写入并通过验证：'+str(service.backups.folder))
    expect(page.locator('#backup-error')).to_be_hidden()
    expect(page.locator('#backup-history-dialog')).to_be_hidden()
    expect(page.locator('#settings-dialog #backup-entries')).to_have_count(0)
    page.locator('#backup-list').click()
    expect(page.locator('#backup-history-dialog')).to_be_visible()
    expect(page.locator('#backup-entries').get_by_role('button',name='恢复此备份',exact=True)).to_have_count(2,timeout=15000)
    expect(page.locator('#backup-history-status')).to_have_text('2 份备份')
    expect(page.locator('#backup-entries')).to_contain_text('数据库与原件已验证')
    expect(page.locator('#backup-entries')).to_contain_text('旧备份目录')
    snapshot=next(entry for entry in service.backups.entries() if entry['folder']==str(service.backups.folder))
    assert snapshot['verification']['state']=='verified'
    assert (service.backups.folder/(snapshot['id']+'.zip')).is_file()
    assert (configured_backup/(old_snapshot['id']+'.zip')).is_file()
    page.locator('[data-backup-verify="'+snapshot['id']+'"]').click()
    expect(page.locator('#toast')).to_contain_text('备份验证通过')
    page.locator('#backup-history-dialog .dialog-head button').click()
    expect(page.locator('#backup-history-dialog')).to_be_hidden()
    expect(page.locator('#settings-dialog')).to_be_visible()
    expect(page.locator('#backup-status')).to_contain_text('0.2 GB')
    history_fixture=page.request.get(base+'/api/backups').json()
    history_fixture['items']=[{**history_fixture['items'][0],'id':f'{i:032x}'} for i in range(24)]
    page.set_viewport_size({'width':500,'height':620})
    page.route('**/api/backups',lambda route:route.fulfill(json=history_fixture))
    try:
     page.locator('#backup-list').click()
     expect(page.locator('#backup-history-status')).to_have_text('24 份备份')
     assert page.locator('#backup-entries').evaluate('el=>el.scrollHeight>el.clientHeight && el.scrollWidth<=el.clientWidth')
     page.locator('#backup-history-dialog .dialog-head button').click()
    finally:
     page.unroute('**/api/backups')
     page.set_viewport_size({'width':1300,'height':1000})
    service.backups.error='Synthetic backup failure';service.backups._save_state(state='error',last_error=service.backups.error,last_attempt='fixture')
    page.evaluate('refresh()');expect(page.locator('#settings-open')).to_have_attribute('data-backup-warning','true');expect(page.locator('#backup-error')).to_be_visible();expect(page.locator('#backup-error')).to_contain_text('Synthetic backup failure');assert service.backups.entries()
    service.backups.error='';service.backups._save_state(state='ready',last_error='')
    page.evaluate('refresh()');expect(page.locator('#backup-error')).to_be_hidden()
    page.locator('#settings-dialog .dialog-head button').click()
    library_location.write({'source':str(service.archive.root),'target':str(destination),
                            'migration':'move-failed','error':'目标磁盘可用空间不足。'})
    page.reload()
    expect(page.locator('#library-migration-message')).to_contain_text('当前仍在使用：'+str(service.archive.root))
    expect(page.locator('#library-migration-message')).to_contain_text('目标磁盘可用空间不足。')
    expect(page.locator('#library-migration-open')).to_be_hidden()
    library_location.write({'active':str(service.archive.root),'completed_migration':'move-complete'})
    page.reload()
    expect(page.locator('#library-migration-message')).to_have_text('记忆已迁移到：'+str(service.archive.root))
    with patch('secretary.attachment_editor.launch') as launch:
     with page.expect_response(lambda response:response.url.endswith('/api/data-directory/open')) as opened:
      page.locator('#library-migration-open').click()
     assert opened.value.ok
     launch.assert_called_once_with(service.archive.root)
    page.locator('#library-migration-dismiss').click()
    expect(page.locator('#library-migration-notice')).to_be_hidden()
    page.reload()
    expect(page.locator('#library-migration-message')).to_have_text('记忆已迁移到：'+str(service.archive.root),timeout=12000)
    expect(page.locator('#library-migration-notice')).to_be_hidden()
    original=service.archive.list()[0]
    service.archive.update(original['id'],title='Changed after backup')
    page.locator('#settings-open').click()
    page.locator('#backup-list').click()
    old_row=page.locator('.backup-history-row').filter(has_text='旧备份目录')
    page.once('dialog',lambda confirmation:confirmation.accept())
    with page.expect_response(lambda response:response.url.endswith('/api/backups/restore')) as restored:
     old_row.get_by_role('button',name='恢复此备份',exact=True).click()
    assert restored.value.ok
    assert service.archive.get(original['id'])['title']=='Original'
    expect(page.locator('#settings-dialog')).to_be_hidden()
    page.locator('#settings-open').click()
    with page.expect_download() as exported:
     download.click()
    with ZipFile(exported.value.path()) as backup_zip:
     assert {'archive.sqlite3','archive.json'} <= set(backup_zip.namelist())
    print('PASS: bilingual directory and backup action layout, full ZIP download, create/verify and restore from a previous folder')
   finally:browser.close()
 finally:server.shutdown();server.server_close();service.close()
