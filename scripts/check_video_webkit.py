"""Use the actual macOS app WKWebView to decode/seek a synthetic local H.264 video."""
import os,sys,tempfile,threading,time,json
from pathlib import Path
from http.server import ThreadingHTTPServer
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary.server import Service,handler
from secretary.desktop_window import create_window
from AppKit import NSApplication
from Foundation import NSRunLoop,NSDate

app=NSApplication.sharedApplication();app.setActivationPolicy_(1)
with tempfile.TemporaryDirectory() as root:
    service=Service(root);service.archive.configure('codex',False)
    clip=(Path(__file__).resolve().parent.parent/'tests/fixtures/video.mp4').read_bytes()
    ident,_=service.archive.add('Synthetic WebKit video',filename='clip.mp4',data=clip)
    server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
    window,view,delegate=create_window(base)
    def pump():NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(.05))
    def js(source):
        result={}
        def finished(value,error):result.update(value=value,error=error)
        view.evaluateJavaScript_completionHandler_(source,finished)
        deadline=time.monotonic()+10
        while not result and time.monotonic()<deadline:pump()
        assert result and not result.get('error'),result
        return result['value']
    def wait(check):
        deadline=time.monotonic()+25
        while time.monotonic()<deadline:
            if check():return
            pump()
        raise AssertionError('WebKit video state timed out')
    try:
        window.makeKeyAndOrderFront_(None)
        wait(lambda:delegate.loaded)
        wait(lambda:js('Boolean(globalThis.StellarVideoViewer&&document.querySelector("#model-label"))'))
        url=f'/api/items/{ident}/preview'
        js('''(()=>{const trigger=document.createElement('button');trigger.dataset.videoSrc='''+json.dumps(url)+''';trigger.dataset.videoName='Synthetic WebKit clip';StellarVideoViewer.open(trigger);const v=document.querySelector('#video-viewer video');v.muted=true;v.play().catch(()=>{});return true})()''')
        wait(lambda:js('(()=>{const v=document.querySelector("#video-viewer video");return v.duration>0&&v.currentTime>.1&&!v.paused})()'))
        js('(()=>{const v=document.querySelector("#video-viewer video");v.pause();v.currentTime=2;return true})()')
        wait(lambda:js('document.querySelector("#video-viewer video").currentTime>=1.9'))
        js('document.querySelector("#video-viewer").close();true')
        wait(lambda:js('(()=>{const v=document.querySelector("#video-viewer video");return v.paused&&!v.hasAttribute("src")})()'))
        print('PASS: actual macOS app WKWebView H.264 playback, Range seek and stop on close; isolated synthetic data')
    finally:
        window.orderOut_(None);view.stopLoading();server.shutdown();server.server_close();service.close()
