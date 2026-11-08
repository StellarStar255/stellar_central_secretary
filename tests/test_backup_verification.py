import hashlib,json,tempfile,unittest,zipfile
from pathlib import Path
from secretary.server import Service
class BackupVerificationTest(unittest.TestCase):
 def rewrite(self,service,entry,change):
  source=service.backups.folder/(entry['id']+'.zip')
  with zipfile.ZipFile(source) as archive:contents={name:archive.read(name) for name in archive.namelist()}
  change(contents)
  with zipfile.ZipFile(source,'w',zipfile.ZIP_DEFLATED) as archive:
   for name,value in contents.items():archive.writestr(name,value)
  meta=source.with_suffix('.json');value=json.loads(meta.read_text());value.update(sha256=hashlib.sha256(source.read_bytes()).hexdigest(),size=source.stat().st_size);meta.write_text(json.dumps(value))
 def test_auto_verification_and_corruption_never_changes_live_library(self):
  with tempfile.TemporaryDirectory() as temp:
   service=Service(temp)
   try:
    ident,_=service.archive.add('original','body',filename='original.txt',data=b'ORIGINAL');entry=service.backups.create();self.assertEqual(entry['verification']['state'],'verified')
    self.assertEqual(entry['verification']['records'],1);self.assertEqual(entry['verification']['mode'],'manifest')
    service.archive.update(ident,title='new title');before=service.archive.export()
    self.rewrite(service,entry,lambda contents:contents.update({'files/'+ident:b'CORRUPT'}))
    with self.assertRaises(ValueError):service.backups.verify(entry['id'])
    self.assertEqual(service.archive.export(),before);self.assertEqual((service.archive.root/'files'/ident).read_bytes(),b'ORIGINAL')
    self.assertEqual(service.backups.entries()[0]['verification']['state'],'failed')
    with self.assertRaises(ValueError):service.backups.restore(entry['id'])
    self.assertEqual(service.archive.export(),before)
   finally:service.close()
 def test_missing_reference_and_legacy_backup(self):
  with tempfile.TemporaryDirectory() as temp:
   service=Service(temp)
   try:
    ident,_=service.archive.add('file','body',filename='original.txt',data=b'ORIGINAL');entry=service.backups.create()
    self.rewrite(service,entry,lambda contents:contents.pop('manifest.json'));self.assertEqual(service.backups.verify(entry['id'])['verification']['mode'],'legacy')
    self.rewrite(service,entry,lambda contents:contents.pop('files/'+ident))
    with self.assertRaisesRegex(ValueError,'缺少原件'):service.backups.verify(entry['id'])
   finally:service.close()
 def test_failed_new_backup_keeps_previous_verified_snapshot(self):
  with tempfile.TemporaryDirectory() as temp:
   service=Service(temp)
   try:
    ident,_=service.archive.add('file','body',filename='original.txt',data=b'ORIGINAL');service.backups.other_keep=1;entry=service.backups.create()
    (service.archive.root/'files'/ident).write_bytes(b'SOURCE CORRUPTION')
    with self.assertRaisesRegex(ValueError,'校验值不一致'):service.backups.create()
    self.assertTrue((service.backups.folder/(entry['id']+'.zip')).exists());self.assertEqual(service.backups.status()['state'],'error')
   finally:service.close()

 def test_restore_good_backup_preserves_but_does_not_certify_corrupt_current_source(self):
  with tempfile.TemporaryDirectory() as temp:
   service=Service(temp)
   try:
    ident,_=service.archive.add('file','body',filename='original.txt',data=b'ORIGINAL');entry=service.backups.create();path=service.archive.root/'files'/ident;path.write_bytes(b'EXTERNAL MODIFICATION')
    service.backups.restore(entry['id']);self.assertEqual(path.read_bytes(),b'ORIGINAL')
    preserved=next(value for value in service.backups.entries() if value['reason']=='before-restore');self.assertEqual(preserved['verification']['state'],'inconsistent')
    with zipfile.ZipFile(service.backups.folder/(preserved['id']+'.zip')) as archive:self.assertEqual(archive.read('files/'+ident),b'EXTERNAL MODIFICATION')
   finally:service.close()
