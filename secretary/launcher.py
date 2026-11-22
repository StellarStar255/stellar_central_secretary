"""Double-click entry point for the frozen local web application."""
import os
import argparse
import time
from pathlib import Path
import sys
import traceback
import urllib.request
import json
import webbrowser
from . import library_location, paths
from .system_integration import open_browser

def desktop_session(platform=None,env=None):
    platform=sys.platform if platform is None else platform;env=os.environ if env is None else env
    return platform in ('darwin','win32') or platform.startswith('linux') and bool(env.get('DISPLAY') or env.get('WAYLAND_DISPLAY'))


def main():
    # A status probe alone is not a single-instance guard: HTTP becomes available
    # before Qt publishes its desktop state, especially just after an upgrade.
    explicit_desktop = '--desktop' in sys.argv
    desktop = desktop_session() and (explicit_desktop or '--no-browser' not in sys.argv)
    if sys.platform != 'win32' or not desktop:
        return _main()
    from .windows_instance import DesktopSlot, acquire_or_activate
    probe = argparse.ArgumentParser(add_help=False)
    probe.add_argument('--port', type=int, default=8768)
    probe.add_argument('--data-dir')
    known, _ = probe.parse_known_args()
    address = 'http://127.0.0.1:'+str(known.port)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def activate():
        try:
            with opener.open(address+'/api/status', timeout=2) as response:
                status = json.load(response)
            if status.get('application') != 'stellar-central-secretary':
                return False
            if known.data_dir and library_location.selected(library_location.read(), known.data_dir) != Path(status.get('data_dir', '')).resolve():
                raise RuntimeError('此端口已有使用其他资料目录的实例，请使用不同端口。')
            if not status.get('desktop', {}).get('supports_window'):
                return False
            if '--no-browser' not in sys.argv:
                request = urllib.request.Request(address+'/api/interface', data=json.dumps({'mode':status['settings'].get('interface_mode','desktop')}).encode(), headers={'Content-Type':'application/json','X-Knowledge-Token':status['token']})
                opener.open(request, timeout=3).close()
            return True
        except (OSError, ValueError):
            return False
    slot = DesktopSlot(known.port)
    try:
        if acquire_or_activate(slot, activate):
            return _main()
    finally:
        slot.close()


def _main():
    paths.configure_tls()
    explicit_desktop = '--desktop' in sys.argv
    if explicit_desktop: sys.argv.remove('--desktop')
    desktop = desktop_session() and (explicit_desktop or '--no-browser' not in sys.argv)
    probe=argparse.ArgumentParser(add_help=False);probe.add_argument('--port',type=int,default=8768);probe.add_argument('--data-dir');known,_=probe.parse_known_args()
    # Finder launches with a short PATH; Node-based model CLIs use /usr/bin/env.
    os.environ['PATH'] = os.pathsep.join([str(Path.home()/'.local/bin'),
                                        '/opt/homebrew/bin', '/usr/local/bin', os.environ.get('PATH', '')])
    address='http://127.0.0.1:'+str(known.port)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(address+'/api/status', timeout=2) as response:
            status = json.load(response)
        if status.get('application') == 'stellar-central-secretary' and (not known.data_dir or library_location.selected(library_location.read(), known.data_dir)==Path(status.get('data_dir','')).resolve()):
            if desktop and not status.get('desktop', {}).get('enabled'):
                if sys.platform=='win32' and not status.get('capabilities',{}).get('desktop_bridge'):
                    active=any(status.get('runtime',{}).values()) or status.get('update',{}).get('phase') in ('downloading','verifying','installing')
                    if active:
                        try:
                            import ctypes
                            ctypes.windll.user32.MessageBoxW(None,'An older instance is busy. Finish its tasks, then open Stellar Secretary again to enable desktop mode.','Stellar Secretary',0x40)
                        except Exception:pass
                        if '--no-browser' not in sys.argv:open_browser(address)
                        return
                    request=urllib.request.Request(address+'/api/shutdown',data=b'{}',headers={'Content-Type':'application/json','X-Knowledge-Token':status['token']})
                    opener.open(request,timeout=5).close()
                    for _ in range(60):
                        try:opener.open(address+'/api/status',timeout=.5).close()
                        except OSError:break
                        time.sleep(.25)
                    else:raise RuntimeError('The older local service has not finished closing')
                    if not known.data_dir:sys.argv+=['--data-dir',status['data_dir']]
                else:
                    if sys.platform=='darwin':
                        from .desktop_macos import run
                    else:
                        from .desktop_qt import run
                    run(address, open_browser='--no-browser' not in sys.argv)
                    return
            if not (desktop and sys.platform=='win32' and not status.get('desktop',{}).get('enabled') and not status.get('capabilities',{}).get('desktop_bridge')) and '--no-browser' not in sys.argv:
                if status.get('desktop',{}).get('supports_window'):
                    request=urllib.request.Request(address+'/api/interface',data=json.dumps({'mode':status['settings'].get('interface_mode','desktop')}).encode(),headers={'Content-Type':'application/json','X-Knowledge-Token':status['token']})
                    opener.open(request,timeout=3).close()
                else:open_browser(address)
            if not (desktop and sys.platform=='win32' and not status.get('desktop',{}).get('enabled') and not status.get('capabilities',{}).get('desktop_bridge')):return
    except (OSError, ValueError):
        pass
    try:
        from .server import main as serve
        recovery = None
        if sys.platform == 'win32' and desktop and not known.data_dir and not os.environ.get('SECRETARY_DATA_DIR'):
            from .library_recovery import choose
            recovery = choose
        serve(desktop=desktop, recover_library=recovery)
    except library_location.Unavailable as error:
        if desktop:
            if sys.platform == 'darwin':
                from AppKit import NSAlert, NSApplication
                NSApplication.sharedApplication()
                alert = NSAlert.alloc().init()
                alert.setMessageText_(str(error))
                alert.runModal()
            else:
                from PySide6.QtWidgets import QApplication, QMessageBox
                app = QApplication.instance() or QApplication([])
                QMessageBox.warning(None, 'Stellar Secretary', str(error))
        else:
            print(error, file=sys.stderr)
    except Exception:
        traceback.print_exc()
        raise


if __name__ == '__main__':main()
