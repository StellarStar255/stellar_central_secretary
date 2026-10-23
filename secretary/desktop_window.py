"""A local-only macOS WKWebView window, with external links kept in the browser."""
import threading
import json
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path


def create_window(address,get_language=lambda:'zh'):
    from .i18n import translate
    tr=lambda text:translate(text,get_language())
    import objc
    from AppKit import (NSApplication,NSWindow,NSWindowStyleMaskTitled,NSWindowStyleMaskClosable,
                        NSWindowStyleMaskMiniaturizable,NSWindowStyleMaskResizable,NSBackingStoreBuffered,
                        NSOpenPanel,NSSavePanel,NSModalResponseOK,NSAlert)
    from Foundation import NSObject,NSURL,NSURLRequest
    from WebKit import WKWebView,WKWebViewConfiguration,WKWebsiteDataStore,WKUserScript
    origin=urllib.parse.urlsplit(address)

    class WindowDelegate(NSObject):
        def webView_didFinishNavigation_(self,view,navigation):self.loaded=True

        def windowShouldClose_(self,window):
            window.orderOut_(None)
            return False

        def webView_decidePolicyForNavigationAction_decisionHandler_(self,view,action,decide):
            url=str(action.request().URL().absoluteString());parsed=urllib.parse.urlsplit(url)
            local=(parsed.scheme,parsed.netloc)==(origin.scheme,origin.netloc)
            if local and (parsed.path=='/api/backup' or parsed.path.endswith('/file')):
                decide(0);self.save_download(url);return
            if not local or action.targetFrame() is None:
                decide(0)
                if parsed.scheme in ('http','https'):webbrowser.open(url)
                return
            decide(1)

        @objc.python_method
        def save_download(self,url):
            name='stellar-knowledge-backup.zip'
            if not url.endswith('/api/backup'):
                try:
                    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    with opener.open(url[:-5],timeout=3) as response:name=json.load(response)['filename']
                except Exception:name=tr('原文件')
            panel=NSSavePanel.savePanel();panel.setNameFieldStringValue_(Path(name).name)
            if panel.runModal()!=NSModalResponseOK:return
            destination=Path(str(panel.URL().path()))
            def download():
                try:
                    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    with opener.open(url,timeout=60) as response:data=response.read()
                    destination.write_bytes(data)
                except Exception as exc:
                    self.error=str(exc)
                    self.performSelectorOnMainThread_withObject_waitUntilDone_('showError:',None,False)
            threading.Thread(target=download,daemon=True).start()

        def showError_(self,sender):
            alert=NSAlert.alloc().init();alert.setMessageText_(tr('下载未完成'));alert.setInformativeText_(self.error);alert.runModal()

        def webView_runOpenPanelWithParameters_initiatedByFrame_completionHandler_(self,view,parameters,frame,complete):
            panel=NSOpenPanel.openPanel();panel.setCanChooseDirectories_(False);panel.setCanChooseFiles_(True)
            panel.setAllowsMultipleSelection_(parameters.allowsMultipleSelection())
            complete(panel.URLs() if panel.runModal()==NSModalResponseOK else None)

        def webView_createWebViewWithConfiguration_forNavigationAction_windowFeatures_(self,view,configuration,action,features):
            url=str(action.request().URL().absoluteString())
            if urllib.parse.urlsplit(url).scheme in ('http','https'):webbrowser.open(url)
            return None

    configuration=WKWebViewConfiguration.alloc().init()
    script=WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_('window.__stellarDesktop=true;',0,True)
    configuration.userContentController().addUserScript_(script)
    configuration.setWebsiteDataStore_(WKWebsiteDataStore.defaultDataStore())
    view=WKWebView.alloc().initWithFrame_configuration_(((0,0),(1200,820)),configuration)
    delegate=WindowDelegate.alloc().init();delegate.loaded=False;view.setNavigationDelegate_(delegate);view.setUIDelegate_(delegate)
    style=NSWindowStyleMaskTitled|NSWindowStyleMaskClosable|NSWindowStyleMaskMiniaturizable|NSWindowStyleMaskResizable
    window=NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(((0,0),(1200,820)),style,NSBackingStoreBuffered,False)
    window.setTitle_(tr('Stellar Secretary · 知识秘书'));window.setMinSize_((760,560));window.setReleasedWhenClosed_(False)
    window.setContentView_(view);window.setDelegate_(delegate);window.center();window.setFrameAutosaveName_('SecretaryMainWindow')
    view.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(address+'/?desktop=1')))
    return window,view,delegate
