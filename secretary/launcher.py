"""Double-click entry point for the frozen local web application."""
import os
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
    desktop = sys.platform == 'darwin' and (explicit_desktop or '--no-browser' not in sys.argv)
    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    log = open(paths.DATA_DIR / 'app.log', 'a', encoding='utf-8', buffering=1)
    sys.stdout = sys.stderr = log
    # Finder launches with a short PATH; Node-based model CLIs use /usr/bin/env.
    os.environ['PATH'] = os.pathsep.join([str(__import__('pathlib').Path.home()/'.local/bin'),
                                        '/opt/homebrew/bin', '/usr/local/bin', os.environ.get('PATH', '')])
    if '--port' not in sys.argv and '--data-dir' not in sys.argv:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open('http://127.0.0.1:8768/api/status', timeout=2) as response:
                status = json.load(response)
            if status.get('application') == 'stellar-central-secretary':
                if desktop and not status.get('desktop', {}).get('enabled'):
                    from .desktop_macos import run
                    run('http://127.0.0.1:8768', open_browser='--no-browser' not in sys.argv)
                    return
                if '--no-browser' not in sys.argv:
                    webbrowser.open('http://127.0.0.1:8768')
                return
        except (OSError, ValueError):
            pass
    try:
        from .server import main as serve
        serve(desktop=desktop)
    except Exception:
        traceback.print_exc()
        raise
