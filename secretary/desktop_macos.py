"""Native macOS menu bar and Dock lifecycle; Cocoa always runs on the main thread."""
import json
import threading
import urllib.request
import webbrowser
from pathlib import Path

from . import __version__, paths
from .desktop_status import presentation


def run(address, service=None, server=None, open_browser=True):
    import objc
    from AppKit import (NSApplication, NSApplicationActivationPolicyRegular, NSStatusBar,
                        NSVariableStatusItemLength, NSMenu, NSMenuItem, NSImage, NSWorkspace,
                        NSAlert, NSTerminateCancel, NSEvent, NSEventTypeApplicationDefined)
    from Foundation import NSObject, NSTimer, NSURL, NSRunLoop, NSRunLoopCommonModes

    stopped = threading.Event()
    state = {'value':{}}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    worker = None
    if server is not None:
        worker = threading.Thread(target=server.serve_forever, name='knowledge-server', daemon=True)
        worker.start()

    def poll():
        while not stopped.is_set():
            try:
                with opener.open(address+'/api/status', timeout=2) as response:
                    value = json.load(response)
                if value.get('application') != 'stellar-central-secretary':
                    raise ValueError('端口已被其他程序占用')
                state['value'] = value
            except Exception as exc:
                previous = state['value']
                state['value'] = {**previous, 'error':str(exc)}
                if worker is None and previous.get('update', {}).get('phase')=='installing':
                    state['exit'] = True
            stopped.wait(2)

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    icons = Path(__file__).parent/'static'/'icons'
    app_icon = NSImage.alloc().initWithContentsOfFile_(str(icons/'app.png'))
    app.setApplicationIconImage_(app_icon)

    class SecretaryDelegate(NSObject):
        @objc.python_method
        def setup(self):
            self.quitting = False
            self.finished = False
            self.accept_reopen = False
            self.last_label = None
            self.images = {}
            self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
            for name in ('ready', 'busy', 'error', 'starting'):
                image = NSImage.alloc().initWithContentsOfFile_(str(icons/f'tray-{name}.png'))
                image.setSize_((18, 18))
                self.images[name] = image
            self.menu = NSMenu.alloc().init()
            self.menu.setAutoenablesItems_(False)
            self.status_label = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_('正在启动…', None, '')
            self.status_label.setEnabled_(False)
            self.menu.addItem_(self.status_label)
            version = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(f'知识秘书 v{__version__}', None, '')
            version.setEnabled_(False)
            self.menu.addItem_(version)
            self.menu.addItem_(NSMenuItem.separatorItem())
            for title, action, key in [('打开知识秘书', 'openMain:', 'o'),
                                        ('打开资料文件夹', 'openFiles:', ''),
                                        ('查看运行日志', 'openLog:', ''),
                                        ('退出知识秘书', 'requestQuit:', 'q')]:
                item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key)
                item.setTarget_(self)
                self.menu.addItem_(item)
            self.status_item.setMenu_(self.menu)
            main_menu = NSMenu.alloc().init()
            app_menu = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_('知识秘书', None, '')
            app_menu.setSubmenu_(self.menu)
            main_menu.addItem_(app_menu)
            app.setMainMenu_(main_menu)
            self.refresh()

        @objc.python_method
        def refresh(self):
            value = state['value']
            label = presentation(value)
            if self.quitting:
                label = {'title':'退出中', 'detail':'正在停止本机服务…', 'icon':'starting', 'badge':'…'}
            if label != self.last_label:
                button = self.status_item.button()
                button.setImage_(self.images[label['icon']])
                button.setTitle_(' '+label['title'])
                button.setToolTip_('知识秘书 · '+label['detail'])
                self.status_label.setTitle_(label['detail'])
                app.dockTile().setBadgeLabel_(label['badge'])
                self.last_label = label
                if service is not None:
                    service.desktop = {'enabled':True, 'menu_bar':True, 'dock':True,
                                       'state':label['icon'], 'label':button.title(),
                                       'dock_badge':app.dockTile().badgeLabel() or '',
                                       'activation_policy':int(app.activationPolicy())}

        def tick_(self, timer):
            if self.finished or state.get('exit') or (worker is not None and not worker.is_alive()):
                app.stop_(None)
                event = NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
                    NSEventTypeApplicationDefined, (0,0), 0, 0, 0, None, 0, 0, 0)
                app.postEvent_atStart_(event, True)
                return
            self.accept_reopen = True
            self.refresh()

        def openMain_(self, sender):
            webbrowser.open(address)

        def openFiles_(self, sender):
            directory = Path(state['value'].get('data_dir', paths.DATA_DIR))
            NSWorkspace.sharedWorkspace().openURL_(NSURL.fileURLWithPath_(str(directory)))

        def openLog_(self, sender):
            directory = Path(state['value'].get('data_dir', paths.DATA_DIR))
            log = directory/'app.log'
            NSWorkspace.sharedWorkspace().openURL_(NSURL.fileURLWithPath_(str(log)))

        def applicationShouldHandleReopen_hasVisibleWindows_(self, application, visible):
            if self.accept_reopen: self.openMain_(None)
            return False

        def applicationShouldTerminate_(self, application):
            self.requestQuit_(None)
            return NSTerminateCancel

        def requestQuit_(self, sender):
            if self.quitting: return
            value = state['value']
            runtime = service.runtime() if service is not None else value.get('runtime', {})
            if not value.get('error') and (any(runtime.values()) or value.get('update', {}).get('phase') in ('downloading', 'verifying', 'installing')):
                alert = NSAlert.alloc().init()
                alert.setMessageText_('仍有任务正在进行')
                alert.setInformativeText_('请等待整理、问答或升级完成；会话读取可在网页中停止后再退出。')
                alert.addButtonWithTitle_('知道了')
                alert.runModal()
                return
            self.quitting = True
            self.refresh()
            threading.Thread(target=self.shutdown, name='knowledge-shutdown', daemon=True).start()

        @objc.python_method
        def shutdown(self):
            try:
                if server is not None:
                    server.shutdown()
                elif state['value'].get('error'):
                    self.finished = True
                    return
                else:
                    value = state['value']
                    request = urllib.request.Request(address+'/api/shutdown', data=b'{}',
                              headers={'Content-Type':'application/json', 'X-Knowledge-Token':value.get('token','')})
                    with opener.open(request, timeout=5): pass
                self.finished = True
            except Exception as exc:
                self.quitting = False
                state['value'] = {**state['value'], 'error':str(exc)}

    delegate = SecretaryDelegate.alloc().init()
    delegate.setup()
    app.setDelegate_(delegate)
    timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(.5, delegate, 'tick:', None, True)
    NSRunLoop.mainRunLoop().addTimer_forMode_(timer, NSRunLoopCommonModes)
    threading.Thread(target=poll, name='knowledge-status', daemon=True).start()
    if open_browser: webbrowser.open(address)
    try:
        app.run()
    finally:
        stopped.set()
        timer.invalidate()
        NSStatusBar.systemStatusBar().removeStatusItem_(delegate.status_item)
        app.dockTile().setBadgeLabel_(None)
        if server is not None:
            server.shutdown()
            worker.join(timeout=5)
