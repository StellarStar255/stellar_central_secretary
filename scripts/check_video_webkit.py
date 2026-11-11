"""Use the actual macOS app WKWebView to decode/seek a synthetic local H.264 video."""
import os,sys,tempfile,threading,time,json
from pathlib import Path
from http.server import ThreadingHTTPServer
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary.server import Service,handler
from secretary.desktop_window import create_window
from secretary import bundles
from AppKit import NSApplication
from Foundation import NSRunLoop,NSDate

app=NSApplication.sharedApplication();app.setActivationPolicy_(1)
with tempfile.TemporaryDirectory() as root:
    service=Service(root);service.archive.configure('codex',False)
    clip=(Path(__file__).resolve().parent.parent/'tests/fixtures/video.mp4').read_bytes()
    ident,_=service.archive.add('Synthetic WebKit video',filename='clip.mp4',data=clip)
    server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
    saved=Path(root)/'saved';saved.mkdir();chosen=[];cancel=[False]
    def choose_download(name):
        chosen.append(name);return None if cancel[0] else saved/name
    window,view,delegate=create_window(base,choose_download=choose_download)
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
        expected_page=js('location.href');js('document.querySelector("[data-video-download]").click();true')
        wait(lambda:(saved/'clip.mp4').exists());assert (saved/'clip.mp4').read_bytes()==clip
        wait(lambda:js('document.querySelector("#video-viewer [data-desktop-download-status]")?.textContent.includes("已保存")'))
        assert js('location.href')==expected_page and js('document.querySelector("#video-viewer").open')
        cancel[0]=True;js('document.querySelector("[data-video-download]").click();true')
        wait(lambda:js('document.querySelector("#video-viewer [data-desktop-download-status]").textContent.includes("已取消")'))
        assert len(chosen)==2 and (saved/'clip.mp4').read_bytes()==clip;cancel[0]=False
        # Grouped and added attachments use the endpoint missed by the old Mac policy.
        raw,text=bundles.create('',[{'name':'同次 视频.mp4','data':__import__('base64').b64encode(clip).decode()}]);group,_=service.archive.add(text=text,filename='materials.stellar.zip',data=raw);bundles.cleanup(raw)
        # Use a distinct byte sequence to retain the added leaf rather than deduplicate it.
        added=service.append_material(group,{'attachments':[{'name':'追加 视频.mp4','data':__import__('base64').b64encode(clip+b'ADDED').decode()}],'expected_updated':service.archive.get(group)['updated'],'summarize':False})['item']
        for file in service.material_attachments(added)['all_attachments']:
            js('document.querySelector("#video-viewer").close();true')
            trigger={'videoSrc':file['preview_url'],'videoName':file['name'],'videoDownload':file['download_url']}
            js('(()=>{const button=document.createElement("button");Object.assign(button.dataset,'+json.dumps(trigger)+');StellarVideoViewer.open(button);return true})()')
            wait(lambda:js('document.querySelector("#video-viewer").open'))
            js('document.querySelector("[data-video-download]").click();true')
            target=saved/file['name'];wait(target.exists);assert target.read_bytes()==clip+(b'ADDED' if file['batch_id'] else b'')
            assert js('location.href')==expected_page
        js('document.querySelector("#video-viewer").close();true')
        wait(lambda:js('(()=>{const v=document.querySelector("#video-viewer video");return v.paused&&!v.hasAttribute("src")})()'))
        fixtures=Path(__file__).resolve().parent.parent/'tests/fixtures'
        live=service.ingest({'attachments':[{'name':name,'data':__import__('base64').b64encode((fixtures/source).read_bytes()).decode()} for name,source in [('live.HEIC','synthetic.heic'),('live.MOV','live-photo.mov')]],'defer_summary':True})['item']
        photo=live['all_attachments'][0]
        js('StellarImageViewer.open([{src:'+json.dumps(photo['preview_url'])+',name:"live.HEIC"}]);true')
        wait(lambda:js('!document.querySelector("[data-viewer=motion]").hidden'))
        js('document.querySelector("#video-viewer video").muted=true;document.querySelector("[data-viewer=motion]").click();true')
        wait(lambda:js('(()=>{const v=document.querySelector("#video-viewer video");return document.querySelector("#video-viewer").open&&v.videoWidth>0&&v.currentTime>.1&&!v.paused})()'))
        js('StellarCloseTopLayer();true')
        wait(lambda:js('!document.querySelector("#video-viewer").open&&document.querySelector("#video-viewer video").paused'))
        assert js('document.querySelector("#image-viewer").open')
        js('StellarCloseTopLayer();true')
        print('PASS: actual Mac HEIC-to-MOV pairing, decoded Live Photo motion and closing playback returns to still photo')
        print('PASS: actual Mac WKWebView playback, original/grouped/added video downloads, Unicode filenames, visible completion/cancel feedback, cancellation preserves files, no navigation away and stop on close')
    finally:
        window.orderOut_(None);view.stopLoading();server.shutdown();server.server_close();service.close()
