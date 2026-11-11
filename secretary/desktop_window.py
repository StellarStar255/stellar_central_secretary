"""A local-only macOS WKWebView window, with external links kept in the browser."""
import threading
import json
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path


def create_window(address,get_language=lambda:'zh',choose_download=None):
    from .i18n import translate
    tr=lambda text:translate(text,get_language())
    import objc
    from AppKit import (NSApplication,NSWindow,NSWindowStyleMaskTitled,NSWindowStyleMaskClosable,
                        NSWindowStyleMaskMiniaturizable,NSWindowStyleMaskResizable,NSBackingStoreBuffered,
                        NSOpenPanel,NSSavePanel,NSModalResponseOK,NSAlert)
    from Foundation import NSObject,NSURL,NSURLRequest
    from WebKit import WKWebView,WKWebViewConfiguration,WKWebsiteDataStore,WKUserScript
    origin=urllib.parse.urlsplit(address)
    from . import desktop_downloads

    class WindowDelegate(NSObject):
        def webView_didFinishNavigation_(self,view,navigation):self.loaded=True

        @objc.python_method
        def close_current_layer(self,window):
            if getattr(self,'closing_layer',False):return
            self.closing_layer=True
            def complete(handled,error):
                self.closing_layer=False
                if error is None and not handled:window.performClose_(None)
            view.evaluateJavaScript_completionHandler_('Boolean(globalThis.StellarCloseTopLayer?.())',complete)

        def windowShouldClose_(self,window):
            window.orderOut_(None)
            return False

        def webView_decidePolicyForNavigationAction_decisionHandler_(self,view,action,decide):
            url=str(action.request().URL().absoluteString());parsed=urllib.parse.urlsplit(url)
            local=(parsed.scheme,parsed.netloc)==(origin.scheme,origin.netloc)
            if desktop_downloads.route(address,url) is not None:
                decide(0);self.save_download(url);return
            if not local or action.targetFrame() is None:
                decide(0)
                if parsed.scheme in ('http','https'):webbrowser.open(url)
                return
            decide(1)

        @objc.python_method
        def notify_download(self,value):
            view.evaluateJavaScript_completionHandler_('document.dispatchEvent(new CustomEvent("stellar-download",{detail:'+json.dumps(value,ensure_ascii=False)+'}));',None)

        @objc.python_method
        def save_download(self,url):
            if url in self.downloads:return
            self.downloads.add(url);self.notify_download({'url':url,'state':'preparing'})
            def prepare():
                try:
                    name=desktop_downloads.filename(address,url)
                    self.performSelectorOnMainThread_withObject_waitUntilDone_('chooseDownload:',{'url':url,'name':name},False)
                except Exception as error:
                    self.performSelectorOnMainThread_withObject_waitUntilDone_('finishDownload:',{'url':url,'state':'error','message':str(error)},False)
            threading.Thread(target=prepare,daemon=True).start()

        def chooseDownload_(self,value):
            url=str(value['url']);name=str(value['name'])
            if choose_download is not None:
                target=choose_download(name)
            else:
                panel=NSSavePanel.savePanel();panel.setNameFieldStringValue_(name);panel.setDirectoryURL_(NSURL.fileURLWithPath_(str(Path.home()/'Downloads')))
                target=Path(str(panel.URL().path())) if panel.runModal()==NSModalResponseOK else None
            if target is None:
                self.finishDownload_({'url':url,'state':'cancelled'});return
            destination=Path(target);self.notify_download({'url':url,'state':'saving','name':name})
            def download():
                try:
                    last=[0]
                    def progress(received,total):
                        import time
                        now=time.monotonic()
                        if now-last[0]<.5:return
                        last[0]=now
                        self.performSelectorOnMainThread_withObject_waitUntilDone_('downloadProgress:',{'url':url,'state':'saving','bytes':received,'total':total or 0},False)
                    result=desktop_downloads.save(address,url,destination,progress)
                    value={'url':url,'state':'complete',**result}
                except Exception as error:value={'url':url,'state':'error','message':str(error)}
                self.performSelectorOnMainThread_withObject_waitUntilDone_('finishDownload:',value,False)
            threading.Thread(target=download,daemon=True).start()

        def downloadProgress_(self,value):self.notify_download(dict(value))

        def finishDownload_(self,value):
            value=dict(value);self.downloads.discard(value['url']);self.notify_download(value)
            if value['state']=='error':
                self.error=value['message'];self.showError_(None)

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
    delegate=WindowDelegate.alloc().init();delegate.loaded=False;delegate.downloads=set();view.setNavigationDelegate_(delegate);view.setUIDelegate_(delegate)
    style=NSWindowStyleMaskTitled|NSWindowStyleMaskClosable|NSWindowStyleMaskMiniaturizable|NSWindowStyleMaskResizable
    window=NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(((0,0),(1200,820)),style,NSBackingStoreBuffered,False)
    window.setTitle_(tr('Stellar Secretary · 知识秘书'));window.setMinSize_((760,560));window.setReleasedWhenClosed_(False)
    window.setContentView_(view);window.setDelegate_(delegate);window.center();window.setFrameAutosaveName_('SecretaryMainWindow')
    view.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(address+'/?desktop=1')))
    return window,view,delegate
