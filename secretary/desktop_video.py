"""In-app Qt Multimedia player, independent of Qt WebEngine's codec build."""
from PySide6.QtCore import Qt,QUrl,QBuffer,QIODevice,QByteArray
from PySide6.QtMultimedia import QAudioOutput,QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QDialog,QHBoxLayout,QLabel,QPushButton,QSlider,QVBoxLayout


class VideoWindow(QDialog):
    def __init__(self,parent,tr,on_external,on_state=None):
        super().__init__(parent);self.on_state=on_state;self.source_path='';self.resume=0;self.last_saved=0;self.poster_saved=False;self.tr_text=tr;self.resize(900,620);self.setObjectName('stellar-video-player')
        layout=QVBoxLayout(self);self.picture=QVideoWidget(self);layout.addWidget(self.picture,1)
        self.message=QLabel(self);self.message.setWordWrap(True);layout.addWidget(self.message)
        controls=QHBoxLayout();layout.addLayout(controls)
        self.toggle=QPushButton(tr('播放 / 暂停'),self);controls.addWidget(self.toggle)
        self.slider=QSlider(Qt.Orientation.Horizontal,self);controls.addWidget(self.slider,1)
        self.clock=QLabel('00:00 / 00:00',self);controls.addWidget(self.clock)
        self.volume=QSlider(Qt.Orientation.Horizontal,self);self.volume.setRange(0,100);self.volume.setValue(80);self.volume.setMaximumWidth(100);self.volume.setAccessibleName(tr('音量'));controls.addWidget(self.volume)
        self.external=QPushButton(tr('默认程序打开'),self);controls.addWidget(self.external)
        self.fullscreen=QPushButton(tr('全屏'),self);controls.addWidget(self.fullscreen);self.fullscreen.clicked.connect(lambda:self.showNormal() if self.isFullScreen() else self.showFullScreen())
        self.external.clicked.connect(lambda:on_external(self.source_path))
        self.player=QMediaPlayer(self);self.audio=QAudioOutput(self);self.audio.setVolume(.8)
        self.player.setAudioOutput(self.audio);self.player.setVideoOutput(self.picture)
        self.volume.valueChanged.connect(lambda value:self.audio.setVolume(value/100))
        self.toggle.clicked.connect(lambda:self.player.pause() if self.player.playbackState()==QMediaPlayer.PlaybackState.PlayingState else self.player.play())
        self.slider.sliderMoved.connect(self.player.setPosition)
        self.player.durationChanged.connect(self.duration)
        self.picture.videoSink().videoFrameChanged.connect(self.frame)
        self.player.positionChanged.connect(self.position)
        self.player.errorOccurred.connect(lambda *_:self.message.setText(tr('当前播放器不支持此视频编码，或文件无法读取。可用默认程序打开，或下载原件。')))
    def duration(self,value):
        self.slider.setRange(0,min(value,2147483647))
        if self.resume and value>0:
            position=self.resume;self.resume=0
            if position<value-min(2000,value*.05):self.player.setPosition(int(position))
        self.persist()
    def persist(self):
        if self.on_state and self.source_path and self.player.duration()>0:
            self.on_state(self.source_path,{'position':self.player.position()/1000,'duration':self.player.duration()/1000})
    def frame(self,frame):
        if self.poster_saved or not self.on_state or not self.source_path or not frame.isValid():return
        image=frame.toImage()
        if image.isNull():return
        self.poster_saved=True;image=image.scaled(480,320,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
        raw=QByteArray();buffer=QBuffer(raw);buffer.open(QIODevice.OpenModeFlag.WriteOnly);image.save(buffer,'JPEG',82)
        import base64
        self.on_state(self.source_path,{'poster':base64.b64encode(bytes(raw)).decode(),'duration':self.player.duration()/1000})
    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Escape and self.isFullScreen():self.showNormal();event.accept();return
        super().keyPressEvent(event)
    def position(self,value):
        if abs(value-self.last_saved)>=5000:self.last_saved=value;self.persist()
        if not self.slider.isSliderDown():self.slider.setValue(value)
        def clock(ms):return f'{ms//60000:02d}:{ms//1000%60:02d}'
        self.clock.setText(clock(value)+' / '+clock(self.player.duration()))
    def open_video(self,url,name,state=None):
        self.persist();self.resume=(state or {}).get("position",0)*1000;self.last_saved=0;self.poster_saved=bool((state or {}).get("poster"))
        self.source_path=QUrl(url).path().removesuffix('/preview')
        self.player.stop();self.message.clear();self.setWindowTitle(name);self.player.setSource(QUrl(url))
        self.show();self.raise_();self.activateWindow();self.player.play()
    def closeEvent(self,event):
        self.persist();self.player.stop();self.player.setSource(QUrl());super().closeEvent(event)
    def done(self,result):
        self.persist();self.player.stop();self.player.setSource(QUrl());super().done(result)
    def status(self):
        return {'visible':self.isVisible(),'window_id':int(self.winId()),'position':self.player.position(),'duration':self.player.duration(),
                'playing':self.player.playbackState()==QMediaPlayer.PlaybackState.PlayingState,'error':self.player.errorString()}
