import tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
from secretary.server import Service

class VisualCacheTest(unittest.TestCase):
 def test_fresh_image_bytes_are_reused_but_changes_and_force_refresh_invalidate(self):
  with tempfile.TemporaryDirectory() as root:
   s=Service(root)
   try:
    item=s.archive.add('Synthetic image','课表')[0];file=Path(root)/'files'/item;file.write_bytes(b'original')
    passages=s.archive.retrieve('课表');builder=Mock(return_value=([{'name':'image','data':b'prepared'}],[{'source':1,'status':'image_attached_for_rechecking'}]))
    cache=s.visual_cache
    self.assertFalse(cache.prepare(s.archive,passages,'codex',builder)[2]);self.assertTrue(cache.prepare(s.archive,passages,'codex',builder)[2]);self.assertEqual(builder.call_count,1)
    file.write_bytes(b'changed original');self.assertFalse(cache.prepare(s.archive,passages,'codex',builder)[2])
    self.assertFalse(cache.prepare(s.archive,passages,'codex',builder,force=True)[2])
    self.assertFalse(cache.prepare(s.archive,passages,{'vision':False},builder)[2])
    s.archive.update(item,text='课表更新');self.assertFalse(cache.prepare(s.archive,passages,'codex',builder)[2])
   finally:s.close()
