import tempfile,time,unittest,json
from contextlib import closing
from unittest.mock import patch
from secretary.core import Archive
from secretary.library import query,dashboard
class LibraryIndexTest(unittest.TestCase):
 def test_ten_thousand_records_use_bounded_pages_and_index(self):
  with tempfile.TemporaryDirectory() as temp:
   archive=Archive(temp)
   with archive.db() as db:
    db.executemany("INSERT INTO items(id,title,kind,url,filename,digest,text,state,created,updated) VALUES(?,?,'note','','',?,?,'saved','2026-01-01','2026-01-01')",[(f'{n:032x}','Synthetic record '+str(n),str(n),'sample body camera record '+str(n)+' 独特中文短语') for n in range(10000)])
   with patch.object(archive,'list',side_effect=AssertionError('Full-library materialization')):
    start=time.monotonic();page=query(archive,offset=9900);self.assertEqual(page['total'],10000);self.assertEqual(len(page['items']),100)
    result=query(archive,q='camera 9876');self.assertEqual([row['id'] for row in result['items']],[f'{9876:032x}'])
    self.assertEqual(query(archive,q='中文')['total'],10000);self.assertEqual(query(archive,q='独特中文')['total'],10000)
    self.assertEqual(len(dashboard(archive,[])['items']),30);self.assertEqual(dashboard(archive,[])['total'],10000)
    elapsed=time.monotonic()-start;self.assertLess(elapsed,15,'Bounded synthetic queries should finish within a generous CI budget')
   print(f'10000-record paged/indexed/short-CJK/dashboard checks: {elapsed:.3f}s')
 def test_all_metadata_writes_refresh_index_and_keep_literal_matching(self):
  with tempfile.TemporaryDirectory() as temp:
   archive=Archive(temp);ident,_=archive.add('Camera','body raw origin')
   self.assertEqual(query(archive,q='amer')['total'],1)
   archive.update(ident,summary='new summary only')
   self.assertEqual(query(archive,q='summary')['total'],1)
   with archive.db() as db:db.execute('UPDATE items SET note=? WHERE id=?',('用户速记 /folder/100%_done',ident))
   self.assertEqual(query(archive,q='100%_done')['total'],1);self.assertEqual(query(archive,q='户速')['total'],1)
   archive.update(ident,text='changed');self.assertEqual(query(archive,q='origin')['total'],0)
   with archive.db() as db:db.execute('UPDATE items SET trashed_at=? WHERE id=?',('now',ident))
   self.assertEqual(query(archive,q='summary')['total'],0)

 def test_old_program_connection_can_write_after_index_migration(self):
  import sqlite3
  with tempfile.TemporaryDirectory() as temp:
   archive=Archive(temp);ident,_=archive.add('Before','original body')
   # This connection has none of the new Python SQL functions, like v0.1.73.
   with closing(sqlite3.connect(archive.root/'archive.sqlite3')) as db,db:db.execute('UPDATE items SET text=? WHERE id=?',('written by an older program',ident))
   self.assertEqual(query(archive,q='older program')['total'],1)
   with closing(sqlite3.connect(archive.root/'archive.sqlite3')) as db,db:db.execute('DELETE FROM items WHERE id=?',(ident,))
   self.assertEqual(query(archive,q='older program')['total'],0)
