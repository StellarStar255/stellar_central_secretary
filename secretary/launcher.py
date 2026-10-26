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
from . import paths


def main():
    paths.configure_tls()
    explicit_desktop = '--desktop' in sys.argv
    if explicit_desktop: sys.argv.remove('--desktop')
    desktop = sys.platform in ('darwin','win32') and (explicit_desktop or '--no-browser' not in sys.argv)
    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    log = open(paths.DATA_DIR / 'app.log', 'a', encoding='utf-8', buffering=1)
    sys.stdout = sys.stderr = log
    # Finder launches with a short PATH; Node-based model CLIs use /usr/bin/env.
    os.environ['PATH'] = os.pathsep.join([str(Path.home()/'.local/bin'),
                                        '/opt/homebrew/bin', '/usr/local/bin', os.environ.get('PATH', '')])
    probe=argparse.ArgumentParser(add_help=False);probe.add_argument('--port',type=int,default=8768);probe.add_argument('--data-dir');known,_=probe.parse_known_args()
    address='http://127.0.0.1:'+str(known.port)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(address+'/api/status', timeout=2) as response:
            status = json.load(response)
        if status.get('application') == 'stellar-central-secretary' and (not known.data_dir or Path(known.data_dir).resolve()==Path(status.get('data_dir','')).resolve()):
            if desktop and not status.get('desktop', {}).get('enabled'):
                if sys.platform=='win32' and not status.get('capabilities',{}).get('desktop_bridge'):
                    active=any(status.get('runtime',{}).values()) or status.get('update',{}).get('phase') in ('downloading','verifying','installing')
                    if active:
                        try:
                            import ctypes
                            ctypes.windll.user32.MessageBoxW(None,'An older instance is busy. Finish its tasks, then open Stellar Secretary again to enable desktop mode.','Stellar Secretary',0x40)
                        except Exception:pass
                        if '--no-browser' not in sys.argv:webbrowser.open(address)
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
                    if sys.platform=='win32':
                        from .desktop_windows import run
                    else:
                        from .desktop_macos import run
                    run(address, open_browser='--no-browser' not in sys.argv)
                    return
            if not (desktop and sys.platform=='win32' and not status.get('desktop',{}).get('enabled') and not status.get('capabilities',{}).get('desktop_bridge')) and '--no-browser' not in sys.argv:
                if status.get('desktop',{}).get('supports_window'):
                    request=urllib.request.Request(address+'/api/interface',data=json.dumps({'mode':status['settings'].get('interface_mode','desktop')}).encode(),headers={'Content-Type':'application/json','X-Knowledge-Token':status['token']})
                    opener.open(request,timeout=3).close()
                else:webbrowser.open(address)
            if not (desktop and sys.platform=='win32' and not status.get('desktop',{}).get('enabled') and not status.get('capabilities',{}).get('desktop_bridge')):return
    except (OSError, ValueError):
        pass
    try:
        from .server import main as serve
        serve(desktop=desktop)
    except Exception:
        traceback.print_exc()
        raise


if __name__ == '__main__':main()
