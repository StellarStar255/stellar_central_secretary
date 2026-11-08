import base64,hashlib,io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from secretary.server import Service
from secretary import bundles,notes,video_state
from secretary.uploads import Uploads

class RecoveryStreamsTest(unittest.TestCase):
    def test_local_snapshot_exact_restore_and_checksum(self):
        with tempfile.TemporaryDirectory() as temp:
            service=Service(temp);archive=service.archive;archive.configure('codex',False)
            try:
                ident,_=archive.add('Before','original text',filename='note.txt',data=b'original text')
                notes.set_note(archive,ident,'private note',[],0)
                (archive.root/'conversations.json').write_text('{"conversations":[],"activeId":""}')
                with archive.db() as db:before=[tuple(row) for row in db.execute('SELECT * FROM items ORDER BY id')]
                saved=service.backups.create('daily')
                archive.update(ident,title='After',text='edited');(archive.root/'files'/ident).write_bytes(b'changed')
                archive.add('Later','later note')
                service.backups.restore(saved['id'])
                with archive.db() as db:self.assertEqual(before,[tuple(row) for row in db.execute('SELECT * FROM items ORDER BY id')])
                self.assertEqual((archive.root/'files'/ident).read_bytes(),b'original text')
                source=service.backups.folder/(saved['id']+'.zip');source.write_bytes(b'corrupted')
                with self.assertRaisesRegex(ValueError,'校验'):service.backups.restore(saved['id'])
                self.assertEqual(archive.get(ident)['title'],'Before')
                service.backups.due();self.assertEqual(len([x for x in service.backups.entries() if x['reason']=='daily' and x.get('verification',{}).get('state')=='verified']),1)
                count=len(service.backups.entries());service.backups.due();self.assertEqual(len(service.backups.entries()),count)
            finally:service.close()

    def test_large_upload_bundle_range_delete_and_backup_without_read_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            service=Service(temp);service.archive.configure('codex',False)
            try:
                source=Path(temp)/'large.mp4'
                with source.open('wb') as stream:stream.truncate(55*1024*1024);stream.seek(-4,2);stream.write(b'TAIL')
                upload=service.uploads.start(source.name,source.stat().st_size)
                offset=0
                with source.open('rb') as stream:
                    while offset<source.stat().st_size:
                        length=min(4*1024*1024,source.stat().st_size-offset)
                        offset=service.uploads.chunk(upload['id'],offset,stream,length)['offset']
                with patch.object(Path,'read_bytes',side_effect=AssertionError('Whole-file read')):
                    item=service.ingest({'attachments':[{'name':source.name,'upload_id':upload['id']}],'archive_only':True})['item']
                    container=service.archive.root/'files'/item['id'];file,member=bundles.member(container,item['attachments'][0]['id'])
                    with member.open() as stream:stream.seek(-4,2);self.assertEqual(stream.read(),b'TAIL')
                    snapshot=service.backups.create();self.assertGreater(snapshot['size'],0)
                    from secretary.backup_import import import_backup
                    from secretary.core import Archive
                    other=Archive(Path(temp)/'imported')
                    self.assertEqual(import_backup(other,service.backups.folder/(snapshot['id']+'.zip'))['imported'],1)
                    self.assertEqual(other.list()[0]['filename'],'materials.stellar.zip')
                    result=service.delete_attachment(item['id'],None,file['id'],{'confirmed':True,'expected_updated':item['updated']})
                    self.assertTrue(result['recovery_saved']);self.assertEqual(service.item_detail(item['id'])['all_attachments'],[])
            finally:service.close()

    def test_upload_offsets_paths_and_content_dedup(self):
        with tempfile.TemporaryDirectory() as temp:
            uploads=Uploads(temp);key=uploads.start('same.txt',5)['id']
            uploads.chunk(key,0,io.BytesIO(b'hello'),5)
            with self.assertRaises(ValueError):uploads.chunk(key,0,io.BytesIO(b'X'),1)
            with self.assertRaises(ValueError):uploads.resolve([{'name':'same.txt','upload_id':'../escape'}])
            with self.assertRaises(ValueError):uploads.resolve([{'name':'other.txt','upload_id':key}])
            data,_=bundles.create('',uploads.resolve([{'name':'same.txt','upload_id':key}])*2)
            try:self.assertEqual(len(bundles.metadata(data)),1)
            finally:bundles.cleanup(data)
            service=Service(Path(temp)/'archive');service.archive.configure('codex',False)
            try:
                encoded=base64.b64encode(b'hello').decode()
                item=service.ingest({'attachments':[{'name':'same.txt','data':encoded}],'archive_only':True})['item']
                with self.assertRaisesRegex(ValueError,'已存在'):service.append_material(item['id'],{'attachments':[{'name':'renamed.txt','data':encoded}],'expected_updated':item['updated'],'summarize':False})
                self.assertEqual(len(service.item_detail(item['id'])['all_attachments']),1)
            finally:service.close()

    def test_video_state_original_identity_and_completion(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'video';source.write_bytes(b'original');key=video_state.identity(temp,source,'id')
            video_state.save(temp,key,{'position':42,'duration':100});self.assertEqual(video_state.read(temp,key)['position'],42)
            video_state.save(temp,key,{'position':99});self.assertEqual(video_state.read(temp,key)['position'],0)
            source.write_bytes(b'replacement');self.assertNotEqual(key,video_state.identity(temp,source,'id'))
            with self.assertRaises(ValueError):video_state.save(temp,key,{'position':float('nan')})
