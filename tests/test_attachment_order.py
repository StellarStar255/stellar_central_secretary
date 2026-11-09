import base64,json,tempfile,unittest,zipfile,io
from pathlib import Path
from secretary import attachment_order,bundles,notes
from secretary.server import Service
from secretary.backup_import import import_backup

class AttachmentOrderTests(unittest.TestCase):
 def test_cross_batch_order_persists_and_backup_remaps_batch_ids(self):
  with tempfile.TemporaryDirectory() as root,tempfile.TemporaryDirectory() as restored:
   service=Service(root);service.archive.configure('codex',False)
   other=Service(restored)
   try:
    files=[{'name':'同名.txt','data':base64.b64encode(data).decode()} for data in (b'FIRST',b'SECOND')]
    raw,_=bundles.create('',files);ident,_=service.archive.add('Ordered item','Original body',filename='materials.stellar.zip',data=raw);bundles.cleanup(raw)
    service.append_material(ident,{'attachments':[{'name':'同名.txt','data':base64.b64encode(b'ADDED').decode()}],'expected_updated':service.archive.get(ident)['updated'],'summarize':False})
    service.archive.update(ident,summary='Keep summary',tags=['manual']);notes.set_note(service.archive,ident,'Keep note',[],0)
    item=service.item_detail(ident);keys=[attachment_order.key(file) for file in item['all_attachments']];order=[keys[2],keys[0],keys[1]]
    before={path.name:path.read_bytes() for path in (Path(root)/'files').iterdir() if path.is_file()}
    service.busy.add(ident) # presentation edits remain possible during summarization
    service.save_attachment_order(ident,{'order':order,'expected_order':keys});service.busy.remove(ident)
    after=service.item_detail(ident)
    self.assertEqual([attachment_order.key(file) for file in after['all_attachments']],order)
    for field in ('text','summary','note','tags','additions'):
     self.assertEqual(item[field],after[field])
    self.assertEqual(before,{path.name:path.read_bytes() for path in (Path(root)/'files').iterdir() if path.is_file()})
    self.assertEqual(service.archive.get(ident)['attachment_order'],order)
    import_backup(other.archive,service.backup());copy=other.item_detail(other.archive.list()[0]['id'])
    self.assertNotEqual(copy['additions'][0]['id'],item['additions'][0]['id'])
    self.assertEqual([file['name'] for file in copy['all_attachments']],['同名.txt']*3)
    self.assertTrue(copy['all_attachments'][0]['batch_id'])
    self.assertEqual(copy['attachment_order'],attachment_order.remap(order,{item['additions'][0]['id']:copy['additions'][0]['id']}))
    service.append_material(ident,{'attachments':[{'name':'new.txt','data':base64.b64encode(b'LAST').decode()}],'expected_updated':after['updated'],'summarize':False})
    current=service.item_detail(ident);self.assertEqual([attachment_order.key(file) for file in current['all_attachments']][:3],order);self.assertEqual(current['all_attachments'][-1]['name'],'new.txt')
    # Deletion filters only the removed identity and retains the others' relative order.
    removed=current['all_attachments'][1];service.delete_attachment(ident,removed['batch_id'],removed['id'],{'confirmed':True,'expected_updated':current['updated']})
    remaining=service.item_detail(ident);self.assertEqual([attachment_order.key(file) for file in remaining['all_attachments']][:2],[order[0],order[2]])
   finally:service.close();other.close()
   reopened=Service(root)
   try:self.assertEqual([attachment_order.key(file) for file in reopened.item_detail(ident)['all_attachments']][:2],[order[0],order[2]])
   finally:reopened.close()

 def test_owned_complete_permutation_and_optimistic_concurrency(self):
  with tempfile.TemporaryDirectory() as root:
   service=Service(root);service.archive.configure('codex',False)
   try:
    ident,_=service.archive.add('Raw original','body',filename='raw.txt',data=b'RAW')
    service.append_material(ident,{'attachments':[{'name':'other.txt','data':base64.b64encode(b'OTHER').decode()}],'expected_updated':service.archive.get(ident)['updated'],'summarize':False})
    keys=[attachment_order.key(file) for file in service.item_detail(ident)['all_attachments']];self.assertEqual(keys[0],'original:original')
    for order in ([keys[0]],keys+[keys[0]],[keys[0],'a'*32+':'+'b'*32],['../../secret'],None):
     with self.assertRaises(ValueError):service.save_attachment_order(ident,{'order':order,'expected_order':keys})
    service.archive.update(ident,summary='Independent summary update')
    service.save_attachment_order(ident,{'order':keys[::-1],'expected_order':keys})
    # The same request is idempotent, but a different stale request is rejected.
    service.save_attachment_order(ident,{'order':keys[::-1],'expected_order':keys})
    with self.assertRaisesRegex(ValueError,'其他窗口'):service.save_attachment_order(ident,{'order':keys,'expected_order':keys})
    self.assertEqual([attachment_order.key(file) for file in service.item_detail(ident)['all_attachments']],keys[::-1])
    service.trash_item(ident,service.archive.get(ident)['updated'])
    with self.assertRaises(KeyError):service.save_attachment_order(ident,{'order':keys,'expected_order':keys[::-1]})
   finally:service.close()

 def test_legacy_backup_without_order_uses_original_sequence(self):
  with tempfile.TemporaryDirectory() as source,tempfile.TemporaryDirectory() as target:
   service=Service(source);other=Service(target)
   try:
    ident,_=service.archive.add('Legacy','text',filename='legacy.txt',data=b'LEGACY')
    raw=service.backup();output=io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as old,zipfile.ZipFile(output,'w') as new:
     for info in old.infolist():
      data=old.read(info.filename)
      if info.filename=='archive.json':
       records=json.loads(data)
       for item in records:item.pop('attachment_order',None)
       data=json.dumps(records).encode()
      new.writestr(info.filename,data)
    import_backup(other.archive,output.getvalue());copy=other.item_detail(other.archive.list()[0]['id']);self.assertEqual(copy['attachment_order'],[]);self.assertEqual(copy['all_attachments'][0]['name'],'legacy.txt')
   finally:service.close();other.close()
