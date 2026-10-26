"""Windows desktop host with a bundled Chromium view and notification-area controls."""
import json,os,sys,threading,urllib.parse,urllib.request,uuid,webbrowser
from pathlib import Path
from .desktop_status import presentation
from .i18n import translate

def local_navigation(address,url):
    source=urllib.parse.urlsplit(address);target=urllib.parse.urlsplit(url)
    return target.scheme in ('http','https') and (source.scheme,source.netloc)==(target.scheme,target.netloc)

def run(address,service=None,server=None,open_browser=True):
    from PySide6.QtCore import QCoreApplication,QEvent,QTimer,QUrl
    from PySide6.QtGui import QAction,QDesktopServices,QIcon
    from PySide6.QtWidgets import QApplication,QFileDialog,QMainWindow,QMenu,QMessageBox,QSystemTrayIcon
    from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile,QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
    if sys.platform=='win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Stellar.Secretary.Desktop')
    app=QApplication.instance() or QApplication([sys.argv[0]])
    app.setApplicationName('Stellar Secretary');app.setQuitOnLastWindowClosed(False)
    icons=Path(__file__).parent/'static'/'icons';app.setWindowIcon(QIcon(str(icons/'app.ico')))
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    state={'value':{},'desktop':{},'errors':0,'exit':False};stopped=threading.Event();owner=uuid.uuid4().hex
    worker=None
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
            if main and url.scheme() in ('http','https'):QDesktopServices.openUrl(url)
            return False
    class Window(QMainWindow):
        exiting=False
        def closeEvent(self,event):
            if self.exiting:event.accept();return
            event.ignore()
            if tray.isSystemTrayAvailable():self.hide()
            else:self.showMinimized()
    window=Window();window.setMinimumSize(760,560)
    area=app.primaryScreen().availableGeometry()
    window.resize(min(1200,max(760,area.width()-80)),min(820,max(560,area.height()-80)))
    window.move(area.center()-window.rect().center())
    view=QWebEngineView(window);page=Page(profile,view);view.setPage(page);window.setCentralWidget(view)
    page.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard,True)
    page.settings().setAttribute(QWebEngineSettings.WebAttribute.PdfViewerEnabled,True)
    def external(request):
        url=request.requestedUrl()
        if url.scheme() in ('http','https'):QDesktopServices.openUrl(url)
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
    def request_mode(mode):
        def change():
            try:post('/api/interface',{'mode':mode})
            except Exception as error:state['mode_error']=str(error)
        threading.Thread(target=change,daemon=True).start()
    for title,callback in [('打开桌面窗口',lambda:request_mode('desktop')),('打开网页模式',lambda:request_mode('browser')),('打开资料目录',lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(root)))),('查看运行日志',lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(root/'app.log'))))]:
        action=menu.addAction(tr(title));action.triggered.connect(callback);actions.append((action,title))
    menu.addSeparator();quitting={'value':False};mode={'value':'desktop','handled':None,'started':False,'browser_opens':0}
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
    shortcut=QAction(window);shortcut.setShortcut('Ctrl+Q');shortcut.triggered.connect(quit_request);window.addAction(shortcut)
    tray.activated.connect(lambda reason:request_mode('desktop') if reason==QSystemTrayIcon.ActivationReason.DoubleClick else None);tray.show()
    def refresh():
        value=state['value'];label=presentation(value);icon=QIcon(str(icons/('tray-'+label['icon']+'.png')))
        tray.setIcon(icon);tray.setToolTip(tr('知识秘书')+' · '+label['detail']);status_action.setText(label['detail'])
        for action,title in actions:action.setText(tr(title))
        window.setWindowTitle(tr('Stellar Secretary · 知识秘书')+' — '+label['title'])
        metadata={'enabled':True,'supports_window':True,'platform':'windows','tray':bool(tray.isVisible() and tray.isSystemTrayAvailable()),'state':label['icon'],'mode':mode['value'],'language':language(),'window_visible':window.isVisible(),'window_minimized':window.isMinimized(),'window_loaded':loaded['value'],'window_id':int(window.winId()),'browser_opens':mode['browser_opens']}
        state['desktop']=metadata
        if service is not None:service.desktop=metadata
    def tick():
        if state['exit'] or worker is not None and not worker.is_alive():app.quit();return
        value=state['value']
        if value and not mode['started']:
            mode['started']=True
            if open_browser:request_mode(value['settings'].get('interface_mode','desktop'))
        request=value.get('interface_request',{})
        if request.get('id') and request['id']!=mode['handled']:
            mode['handled']=request['id'];mode['value']=request['mode']
            if mode['value']=='desktop':window.showNormal();window.raise_();window.activateWindow()
            else:
                window.hide()
                if webbrowser.open(address):mode['browser_opens']+=1
        refresh()
    refresh();view.load(QUrl(address+'/?desktop=1'))
    timer=QTimer();timer.timeout.connect(tick);timer.start(250)
    threading.Thread(target=poll,name='knowledge-status',daemon=True).start()
    try:app.exec()
    finally:
        stopped.set();timer.stop();tray.hide();window.exiting=True;window.close();window.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);profile.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        if server is not None:server.shutdown();worker.join(timeout=5)
        else:
            try:post('/api/desktop/heartbeat',{'owner':owner,'detach':True})
            except Exception:pass
