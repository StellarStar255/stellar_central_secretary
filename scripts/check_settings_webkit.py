"""Exercise the settings dialog in the Mac app's actual WKWebView."""
import sys
import tempfile
import threading
import time
from pathlib import Path

from AppKit import NSApplication
from Foundation import NSDate, NSRunLoop

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from secretary.desktop_window import create_window
from secretary.local_http import LocalHTTPServer
from secretary.server import Service, handler


def pump():
    NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(.05))


def wait(check):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if check():
            return
        pump()
    raise AssertionError('Settings state timed out')


def main():
    NSApplication.sharedApplication().setActivationPolicy_(1)
    with tempfile.TemporaryDirectory() as directory:
        service = Service(directory)
        service.archive.set_language('zh')
        service.archive.set_font_size(24)
        server = LocalHTTPServer(('127.0.0.1', 0), handler(service))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        window, view, delegate = create_window(f'http://127.0.0.1:{server.server_port}')
        window.setFrameAutosaveName_('')

        def js(source):
            result = []
            view.evaluateJavaScript_completionHandler_(source, lambda value, error: result.append((value, error)))
            wait(lambda: result)
            value, error = result[0]
            assert error is None, error
            return value

        def assert_layout():
            layout = js("""(() => {
                const bounds = node => node.getBoundingClientRect();
                const dialog = document.querySelector('#settings-dialog');
                const scroll = dialog.querySelector('.settings-scroll');
                const header = dialog.querySelector('.dialog-head');
                const save = document.querySelector('#settings-save');
                return {
                    width: innerWidth, height: innerHeight, open: dialog.open,
                    bodyHeight: scroll.clientHeight, dialogHeight: bounds(dialog).height,
                    scrollable: scroll.scrollHeight > scroll.clientHeight,
                    pinnedHeader: header.parentElement === dialog && bounds(header).bottom <= bounds(scroll).top + 1,
                    visibleSave: bounds(save).top >= bounds(scroll).bottom && bounds(save).bottom <= innerHeight,
                    visibleDialog: bounds(dialog).top >= 0 && bounds(dialog).bottom <= innerHeight,
                };
            })()""")
            assert layout['open'] and layout['scrollable'] and layout['bodyHeight'] > layout['height'] * .5, layout
            assert abs(layout['dialogHeight'] - layout['height'] * .88) < 2, layout
            assert layout['pinnedHeader'] and layout['visibleSave'] and layout['visibleDialog'], layout

        try:
            window.makeKeyAndOrderFront_(None)
            wait(lambda: delegate.loaded)
            wait(lambda: js("""document.documentElement.lang === 'zh-CN' &&
                getComputedStyle(document.documentElement).fontSize === '24px'"""))
            window.setContentSize_((1200, 820))
            wait(lambda: js('innerHeight === 820'))
            js('document.querySelector("#settings-open").click();true')
            assert_layout()
            window.setContentSize_((800, 560))
            wait(lambda: js('innerHeight === 560'))
            assert_layout()
            assert js("""(() => {
                const scroll = document.querySelector('.settings-scroll');
                const controls = ['#ui-font-size', '#backup-folder'].map(selector => document.querySelector(selector));
                const visible = control => {
                    const rect = control.getBoundingClientRect();
                    return document.elementFromPoint(rect.left + 5, rect.top + rect.height / 2) === control;
                };
                const initial = visible(controls[0]);
                controls[1].scrollIntoView({block:'center'});
                return initial && scroll.scrollTop > 100 && visible(controls[1]);
            })()""")
            assert_layout()
            js('document.querySelector("#summary-language").value="en";document.querySelector("#settings-save").click();true')
            wait(lambda: service.archive.settings()['summary_language'] == 'en')
            wait(lambda: js('!document.querySelector("#settings-dialog").open'))
            js('document.querySelector("#model-open").click();true')
            assert_layout()
            wait(lambda: js('document.querySelector("#summary-language").value === "en"'))
            js("""const language = document.querySelector('#ui-language');
                language.value = 'en'; language.dispatchEvent(new Event('change')); true""")
            wait(lambda: js("""document.documentElement.lang === 'en' &&
                document.querySelector('#settings-save').textContent === 'Save settings'"""))
            assert_layout()
            js('document.querySelector("#settings-dialog .dialog-head button").click();true')
            assert not js('document.querySelector("#settings-dialog").open')
            print('PASS: Mac WKWebView Chinese and English settings, resize, scroll, pinned Save, persisted settings and Close')
        finally:
            window.orderOut_(None)
            view.stopLoading()
            server.shutdown()
            server.server_close()
            service.close()


if __name__ == '__main__':
    main()
