"""Qt desktop host for Windows and Linux with a bundled view and tray controls."""
import json,os,sys,threading,urllib.error,urllib.parse,urllib.request,uuid,webbrowser
from pathlib import Path
from .desktop_status import presentation
from .i18n import translate
from .system_integration import open_browser as launch_browser

def configure_rendering(platform=None,env=None):
    platform=sys.platform if platform is None else platform
    env=os.environ if env is None else env
    if platform!='win32':return
    # Both layers must use software rendering; disabling Chromium's GPU alone
    # still leaves Qt Quick compositing on the Windows graphics driver.
    env['QT_QUICK_BACKEND']='software'
    flags=env.get('QTWEBENGINE_CHROMIUM_FLAGS','')
    if '--disable-gpu' not in flags.split():
        env['QTWEBENGINE_CHROMIUM_FLAGS']=(flags+' --disable-gpu').strip()

def local_navigation(address,url):
    source=urllib.parse.urlsplit(address);target=urllib.parse.urlsplit(url)
    return target.scheme in ('http','https') and (source.scheme,source.netloc)==(target.scheme,target.netloc)

def run(address,service=None,server=None,open_browser=True):
    configure_rendering()
    from PySide6.QtCore import QCoreApplication,QEvent,QTimer,QUrl
    from PySide6.QtGui import QAction,QDesktopServices,QIcon
    from PySide6.QtWidgets import QApplication,QFileDialog,QMainWindow,QMenu,QMessageBox,QSystemTrayIcon
    from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile,QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
    try:
        from .desktop_video import VideoWindow
    except ImportError as error:
        VideoWindow=None
        print('Native video unavailable; using the inline player:',error,flush=True)
    if sys.platform=='win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Stellar.Secretary.Desktop')
    app=QApplication.instance() or QApplication([sys.argv[0]])
    linux=sys.platform.startswith('linux')
    app.setApplicationName('stellar-secretary' if linux else 'Stellar Secretary');app.setQuitOnLastWindowClosed(False)
    if linux:app.setDesktopFileName('stellar-secretary')
    icons=Path(__file__).parent/'static'/'icons';app.setWindowIcon(QIcon(str(icons/('app.png' if linux else 'app.ico'))))
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    state={'value':{},'desktop':{},'errors':0,'exit':False};stopped=threading.Event();owner=uuid.uuid4().hex
    mode={'value':'desktop','handled':None,'started':False,'browser_opens':0,'panel':None,'video_id':None,'video':None}
    worker=None
    # Publish/claim ownership before exposing HTTP or opening the shared Chromium
    # profile. A rejected peer must never keep running as another tray host.
    state['desktop']={'enabled':True,'supports_window':True,'platform':'linux' if linux else 'windows','mode':'desktop','state':'starting'}
    if service is not None:service.desktop=dict(state['desktop'])
    else:
        with opener.open(address+'/api/status',timeout=3) as response:state['value']=json.load(response)
        request=urllib.request.Request(address+'/api/desktop/heartbeat',data=json.dumps({'owner':owner,'desktop':state['desktop']}).encode(),headers={'Content-Type':'application/json','X-Knowledge-Token':state['value'].get('token','')})
        try:opener.open(request,timeout=5).close()
        except urllib.error.HTTPError:
            # Another host won the lease while this launcher was starting.
            with opener.open(address+'/api/status',timeout=3) as response:current=json.load(response)
            if not current.get('desktop',{}).get('supports_window'):raise
            if open_browser:
                request=urllib.request.Request(address+'/api/interface',data=json.dumps({'mode':current['settings'].get('interface_mode','desktop')}).encode(),headers={'Content-Type':'application/json','X-Knowledge-Token':current['token']})
                opener.open(request,timeout=3).close()
            return
    if server is not None:
        if service is not None:
            with service.archive.db() as db:configured=db.execute("SELECT 1 FROM settings WHERE key='interface_mode'").fetchone()
            if not configured:service.archive.set_interface_mode('desktop')
        worker=threading.Thread(target=server.serve_forever,name='knowledge-server',daemon=True);worker.start()
    def post(path,body):
        request=urllib.request.Request(address+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json','X-Knowledge-Token':state['value'].get('token','')})
        with opener.open(request,timeout=5) as response:return json.load(response)
    def poll():
        while not stopped.is_set():
            try:
                with opener.open(address+'/api/status',timeout=2) as response:value=json.load(response)
                if value.get('application')!='stellar-central-secretary':raise ValueError('Unexpected local service')
                state['value']=value
                if service is None and state['desktop']:post('/api/desktop/heartbeat',{'owner':owner,'desktop':state['desktop']})
                state['errors']=0
            except urllib.error.HTTPError as error:
                # Losing the desktop lease is terminal, not a transient network
                # failure. Do not leave a rejected tray sharing the same profile.
                state['errors']+=1
                if service is None and error.code in (400,409) or state['errors']>=5 and state['value']:state['exit']=True
            except Exception:
                state['errors']+=1
                if state['errors']>=5 and state['value']:state['exit']=True
            stopped.wait(.5)
    # Use the same data directory as the local service, including when attaching to it.
    if service is not None:root=service.archive.root
    else:
        with opener.open(address+'/api/status',timeout=3) as response:state['value']=json.load(response)
        root=Path(state['value']['data_dir'])
    profile=QWebEngineProfile('StellarSecretary',app)
    profile.setPersistentStoragePath(str(root/'desktop-webview'))
    profile.setCachePath(str(root/'desktop-webview-cache'))
    class Page(QWebEnginePage):
        def acceptNavigationRequest(self,url,kind,main):
            if url.toString()=='about:blank' or local_navigation(address,url.toString()):return True
            if main and url.scheme() in ('http','https'):launch_browser(url.toString()) if linux else QDesktopServices.openUrl(url)
            return False
    class Window(QMainWindow):
        exiting=False
        def closeEvent(self,event):
            if self.exiting:event.accept();return
            event.ignore()
            if linux:self.showMinimized()
            elif tray.isSystemTrayAvailable():self.hide()
            else:self.showMinimized()
        def changeEvent(self,event):
            super().changeEvent(event)
            if linux and event.type()==QEvent.Type.WindowStateChange and not self.isMinimized() and mode['started'] and mode['value']=='browser':request_mode('desktop')
    window=Window();window.setMinimumSize(760,560)
    window.setObjectName('stellar-main-window')
    area=app.primaryScreen().availableGeometry()
    window.resize(min(1200,max(760,area.width()-80)),min(820,max(560,area.height()-80)))
    window.move(area.center()-window.rect().center())
    view=QWebEngineView(window);page=Page(profile,view);view.setPage(page);window.setCentralWidget(view)
    page.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard,True)
    page.settings().setAttribute(QWebEngineSettings.WebAttribute.PdfViewerEnabled,True)
    def external(request):
        url=request.requestedUrl()
        if url.scheme() in ('http','https'):launch_browser(url.toString()) if linux else QDesktopServices.openUrl(url)
    page.newWindowRequested.connect(external)
    loaded={'value':False};view.loadFinished.connect(lambda ok:loaded.update(value=bool(ok)))
    def language():return state['value'].get('settings',{}).get('ui_language','zh')
    tr=lambda text:translate(text,language())
    def download(request):
        name=Path(request.suggestedFileName() or 'download').name
        target,_=QFileDialog.getSaveFileName(window,tr('保存文件'),str(Path.home()/'Downloads'/name))
        if not target:request.cancel();return
        destination=Path(target);request.setDownloadDirectory(str(destination.parent));request.setDownloadFileName(destination.name);request.accept()
    profile.downloadRequested.connect(download)
    tray=QSystemTrayIcon(QIcon(str(icons/'tray-starting.png')),app);menu=QMenu();tray.setContextMenu(menu)
    status_action=menu.addAction(tr('启动中'));status_action.setEnabled(False);menu.addSeparator()
    actions=[]
    def request_mode(mode,panel=None):
        def change():
            try:post('/api/interface',{'mode':mode,'panel':panel})
            except Exception as error:state['mode_error']=str(error)
        threading.Thread(target=change,daemon=True).start()
    def open_file(path):
        if linux:launch_browser(QUrl.fromLocalFile(str(path)).toString())
        else:QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
    for title,callback in [('打开桌面窗口',lambda:request_mode('desktop')),('打开网页模式',lambda:request_mode('browser')),
                           ('模型与设置',lambda:request_mode(mode['value'],'settings')),('检查更新',lambda:request_mode(mode['value'],'updates')),
                           ('打开资料目录',lambda:open_file(root)),('查看运行日志',lambda:open_file(root/'app.log'))]:
        action=menu.addAction(tr(title));action.triggered.connect(callback);actions.append((action,title))
    menu.addSeparator();quitting={'value':False}
    def quit_request():
        if quitting['value']:return
        value=state['value'];phase=value.get('update',{}).get('phase')
        if phase=='installing':QMessageBox.information(window,tr('正在安装升级'),tr('安装程序正在替换应用文件，请等待完成后退出。'));return
        force=bool(any(value.get('runtime',{}).values()) or phase in ('downloading','verifying'))
        if force:
            box=QMessageBox(window);box.setWindowTitle(tr('仍有任务正在进行'));box.setText(tr('可以停止当前读取、整理和问答并退出。已保存的资料会保留，未完成的结果不会入库，已有浏览器窗口保持打开。'))
            keep=box.addButton(tr('继续运行'),QMessageBox.ButtonRole.RejectRole);stop=box.addButton(tr('停止任务并退出'),QMessageBox.ButtonRole.AcceptRole);box.setDefaultButton(keep);box.exec()
            if box.clickedButton()!=stop:return
        quitting['value']=True
        def shutdown():
            try:post('/api/shutdown',{'force':force})
            except Exception:state['exit']=True
        threading.Thread(target=shutdown,daemon=True).start()
    quit_action=menu.addAction(tr('退出知识秘书'));quit_action.triggered.connect(quit_request);actions.append((quit_action,'退出知识秘书'))
    app_menu=window.menuBar().addMenu(tr('知识秘书')) if linux else None
    if app_menu is not None:
        for action,_ in actions:app_menu.addAction(action)
    shortcut=QAction(window);shortcut.setShortcut('Ctrl+Q');shortcut.triggered.connect(quit_request);window.addAction(shortcut)
    tray.activated.connect(lambda reason:request_mode('desktop') if reason==QSystemTrayIcon.ActivationReason.DoubleClick or linux and reason==QSystemTrayIcon.ActivationReason.Trigger else None);tray.show()
    app.aboutToQuit.connect(tray.hide)
    def refresh():
        value=state['value'];label=presentation(value);icon=QIcon(str(icons/('tray-'+label['icon']+'.png')))
        tray.setIcon(icon);tray.setToolTip(tr('知识秘书')+' · '+label['detail']);status_action.setText(label['detail'])
        for action,title in actions:action.setText(tr(title))
        if app_menu is not None:app_menu.setTitle(tr('知识秘书'))
        window.setWindowTitle(tr('Stellar Secretary · 知识秘书')+' — '+label['title'])
        metadata={'enabled':True,'supports_window':True,'platform':'linux' if linux else 'windows','dock':linux and window.isVisible(),'tray':bool(tray.isVisible() and tray.isSystemTrayAvailable()),'state':label['icon'],'mode':mode['value'],'language':language(),'window_visible':window.isVisible(),'window_minimized':window.isMinimized(),'window_loaded':loaded['value'],'window_id':int(window.winId()),'browser_opens':mode['browser_opens']}
        state['desktop']=metadata
        metadata['video_player']=VideoWindow is not None
        if mode['video'] is not None:metadata['video_status']=mode['video'].status()
        if service is not None:service.desktop=metadata
    def tick():
        if state['exit'] or worker is not None and not worker.is_alive():window.exiting=True;app.quit();return
        value=state['value']
        video_request=value.get('video_request',{})
        if video_request.get('id') and video_request['id']!=mode['video_id']:
            mode['video_id']=video_request['id']
            import re
            if VideoWindow is not None and re.fullmatch(r'/api/items/[a-f0-9]{32}(?:/(?:additions/[a-f0-9]{32}/)?attachments/[a-f0-9]{32})?/preview',video_request.get('url','')):
                if mode['video'] is None:
                    def open_external(path):
                        def launch():
                            try:post(path+'/editor/open',{})
                            except Exception as error:print('Video external open failed:',error,flush=True)
                        threading.Thread(target=launch,daemon=True).start()
                    def save_video(path,body):
                        if service is not None:
                            from .video_state import save
                            try:save(service.archive.root,service.video_identity(path),body)
                            except Exception as error:print('Video state save failed:',error,flush=True)
                        else:
                            def save_remote():
                                try:post(path+'/video-state',body)
                                except Exception as error:print('Video state save failed:',error,flush=True)
                            threading.Thread(target=save_remote,daemon=True).start()
                    mode['video']=VideoWindow(window,tr,open_external,save_video)
                mode['video'].open_video(address+video_request['url'],video_request.get('name',tr('视频播放器')),video_request.get('state',{}))
        if value and not mode['started']:
            mode['started']=True
            if open_browser:request_mode(value['settings'].get('interface_mode','desktop'))
        request=value.get('interface_request',{})
        if request.get('id') and request['id']!=mode['handled']:
            mode['handled']=request['id'];mode['value']=request['mode']
            if mode['value']=='desktop':
                window.showNormal();window.raise_();window.activateWindow();mode['panel']=request.get('panel')
            else:
                if linux:window.showMinimized()
                else:window.hide()
                url=address+('/?'+urllib.parse.urlencode({'panel':request['panel']}) if request.get('panel') else '')
                if launch_browser(url):mode['browser_opens']+=1
        if mode['panel'] and loaded['value']:
            page.runJavaScript('globalThis.StellarOpenPanel?.('+json.dumps(mode['panel'])+');');mode['panel']=None
        refresh()
    refresh();view.load(QUrl(address+'/?desktop=1'))
    timer=QTimer();timer.timeout.connect(tick);timer.start(250)
    threading.Thread(target=poll,name='knowledge-status',daemon=True).start()
    try:app.exec()
    finally:
        print('Desktop shutdown: disposing window',flush=True)
        if mode['video'] is not None:mode['video'].close()
        stopped.set();timer.stop();tray.hide();window.exiting=True;window.close();window.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        print('Desktop shutdown: disposing browser profile',flush=True)
        profile.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        print('Desktop shutdown: stopping service',flush=True)
        if server is not None:server.shutdown();worker.join(timeout=5)
        else:
            try:post('/api/desktop/heartbeat',{'owner':owner,'detach':True})
            except Exception:pass
