import json,tempfile,time,unittest
from pathlib import Path
from secretary.server import Service
class StorageTest(unittest.TestCase):
 def test_preview_selection_staleness_and_protected_files(self):
  with tempfile.TemporaryDirectory() as temp:
   service=Service(Path(temp)/'data')
   try:
    ident,_=service.archive.add('original','body',filename='keep.txt',data=b'KEEP')
    recent=service.uploads.start('recent.bin',10);old=service.uploads.start('expired.bin',10);path=service.uploads.path(old['id']);path.write_bytes(b'expired');meta=path.with_suffix('.json');value=json.loads(meta.read_text());value['updated']=time.time()-90000;meta.write_text(json.dumps(value))
    first=service.backups.create();latest=service.backups.create()
    overview=service.storage.overview();self.assertGreaterEqual(overview['groups']['originals']['bytes'],4)
    plan=service.storage.preview();self.assertEqual({entry['kind'] for entry in plan['items']},{'uploads','backups'})
    upload=next(entry for entry in plan['items'] if entry['kind']=='uploads');self.assertFalse(any('paths' in entry for entry in plan['items']))
    path.write_bytes(b'changed')
    with self.assertRaises(ValueError):service.storage.clean({'token':plan['token'],'ids':[upload['id']],'confirmed':True})
    self.assertTrue(path.exists());plan=service.storage.preview();upload=next(entry for entry in plan['items'] if entry['kind']=='uploads')
    service.busy.add(ident)
    with self.assertRaises(ValueError):service.storage.clean({'token':plan['token'],'ids':[upload['id']],'confirmed':True})
    service.busy.clear();result=service.storage.clean({'token':plan['token'],'ids':[upload['id']],'confirmed':True});self.assertEqual(len(result['removed']),1)
    self.assertFalse(path.exists());self.assertTrue(service.uploads.path(recent['id']).exists());self.assertTrue((service.archive.root/'files'/ident).exists())
    self.assertEqual(len(service.backups.entries()),2)
    plan=service.storage.preview();self.assertEqual(len(plan['items']),1);service.storage.clean({'token':plan['token'],'ids':[plan['items'][0]['id']],'confirmed':True});self.assertEqual([entry['id'] for entry in service.backups.entries()],[latest['id']])
   finally:service.close()
 def test_symlinked_upload_is_never_offered(self):
  with tempfile.TemporaryDirectory() as temp:
   service=Service(Path(temp)/'data')
   try:
    value=service.uploads.start('link.bin',10);path=service.uploads.path(value['id']);path.unlink();outside=Path(temp)/'outside';outside.write_bytes(b'keep')
    try:path.symlink_to(outside)
    except OSError:self.skipTest('symlinks unavailable')
    meta=path.with_suffix('.json');data=json.loads(meta.read_text());data['updated']=time.time()-90000;meta.write_text(json.dumps(data))
    self.assertFalse(service.storage.preview()['items']);self.assertEqual(outside.read_bytes(),b'keep')
   finally:service.close()

 def test_recovery_cleanup_only_removes_selected_history(self):
  with tempfile.TemporaryDirectory() as temp:
   service=Service(temp)
   try:
    from secretary import attachment_delete,attachment_recovery
    ident,_=service.archive.add('deleted leaf','description',filename='remove.txt',data=b'RECOVER')
    attachment_delete.remove(service.archive,ident,None,None,{'confirmed':True,'expected_updated':service.archive.get(ident)['updated']})
    self.assertEqual(len(attachment_recovery.public(service.archive,ident)),1)
    plan=service.storage.preview();choice=next(value for value in plan['items'] if value['kind']=='deleted_attachments')
    service.archive.update(ident,title='new title')
    result=service.storage.clean({'token':plan['token'],'ids':[choice['id']],'confirmed':True})
    self.assertEqual(len(result['removed']),1);self.assertFalse(attachment_recovery.public(service.archive,ident));self.assertEqual(service.archive.get(ident)['title'],'new title')
   finally:service.close()

 def test_backup_folder_alias_is_counted_and_cleaned_once(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp).resolve()
   actual=root/'library'
   actual.mkdir()
   alias=root/'alias'
   try:alias.symlink_to(actual,target_is_directory=True)
   except OSError:self.skipTest('directory symlinks unavailable')
   service=Service(alias)
   try:
    backups=service.backups
    older=backups.create()
    backups.configure({'folder':str(actual/'local-backups')})
    latest=backups.create()
    self.assertEqual(backups.folders(),[backups.folder])
    self.assertEqual({e['id']:e['folder'] for e in backups.entries()},
                     {e['id']:str(backups.folder) for e in (older,latest)})
    self.assertEqual(len(backups.entries()),2)
    preview=service.storage.preview()
    physical=[p for p in backups.folder.rglob('*') if p.is_file()]
    self.assertEqual(preview['overview']['groups']['backups'],
                     {'files':len(physical),'bytes':sum(p.stat().st_size for p in physical)})
    self.assertEqual(preview['overview']['total_bytes'],sum(p.stat().st_size for p in actual.rglob('*') if p.is_file()))
    candidate,=preview['items']
    self.assertNotIn('backup_folder',candidate)
    result=service.storage.clean({'token':preview['token'],'ids':[candidate['id']],'confirmed':True})
    self.assertEqual(result['failed'],[])
    self.assertEqual([e['id'] for e in backups.entries()],[latest['id']])
    self.assertEqual(backups.verify(latest['id'])['verification']['state'],'verified')
   finally:service.close()

 def test_latest_copy_in_old_folder_does_not_protect_extra_copy_elsewhere(self):
  from shutil import copyfile
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp).resolve()
   service=Service(root/'data')
   try:
    backups=service.backups
    old=backups.folder
    snapshot=backups.create()
    backups.configure({'folder':str(root/'external')})
    for suffix in ('.zip','.json'):
     name=snapshot['id']+suffix
     copyfile(old/name,backups.folder/name)
    backups.create()
    plan=service.storage.preview()
    candidate,=plan['items']
    self.assertEqual(candidate['backup_folder'],str(backups.folder))
    service.storage.clean({'token':plan['token'],'ids':[candidate['id']],'confirmed':True})
    self.assertTrue(backups.restore(snapshot['id'],folder=str(old))['ok'])
   finally:service.close()
