"""Native stop callbacks must not overwrite the final saved playback position."""
import importlib.util,os,unittest
from unittest.mock import Mock

@unittest.skipUnless(importlib.util.find_spec('PySide6'),'Qt native playback platform')
class NativeVideoStateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])
    def test_stop_retains_position_even_when_stop_emits_position_zero(self):
        from secretary.desktop_video import VideoWindow
        writes=[];window=VideoWindow(None,lambda value:value,lambda *_:None,lambda path,body:writes.append(body))
        window.active=True;window.source_path='/api/items/'+'a'*32;window.last_saved=40000
        player=Mock();player.duration.return_value=120000;player.position.return_value=42000
        def stop():player.position.return_value=0;window.position(0)
        player.stop.side_effect=stop;window.player=player
        window.stop_playback()
        self.assertEqual([value['position'] for value in writes],[42])
        window.close()
    def test_resume_seeks_after_duration_becomes_available(self):
        from secretary.desktop_video import VideoWindow
        window=VideoWindow(None,lambda value:value,lambda *_:None)
        window.resume=42000;window.player=Mock();window.duration(120000)
        window.player.setPosition.assert_called_once_with(42000)
        window.close()

    def test_silent_probe_decodes_cover_without_opening_a_window(self):
        import time
        from pathlib import Path
        from PySide6.QtCore import QObject
        from secretary.desktop_video import VideoProbe
        writes=[];parent=QObject();probe=VideoProbe(parent,lambda path,body:writes.append(body))
        probe.enqueue((Path(__file__).parent/'fixtures/video.mp4').resolve().as_uri())
        deadline=time.monotonic()+10
        while not writes and time.monotonic()<deadline:self.app.processEvents();time.sleep(.01)
        probe.stop();self.assertTrue(writes,'Silent decoder did not finish')
        self.assertTrue(writes[0].get('poster'),writes);self.assertGreater(writes[0]['duration'],0)
