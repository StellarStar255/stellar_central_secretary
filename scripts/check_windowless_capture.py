"""Regression: attach to windowless Chrome, then read a conversation and a web page.

Uses a temporary profile and synthetic local content; no accounts or AI calls.
"""
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.sync_api import sync_playwright
from secretary import browser_reader as reader, capture_browser, web_reader

BODY = '''<!doctype html><meta charset="utf-8"><title>Capture regression</title><main>
<article data-testid="conversation-turn-1" data-turn="user">
<div data-message-author-role="user">Why did the conversation capture fail?</div></article>
<article data-testid="conversation-turn-2" data-turn="assistant">
<div data-message-author-role="assistant">The browser connection must preserve the persistent context settings before reading this synthetic conversation.</div></article>
</main>'''

VISIBILITY_BODY = '''<!doctype html><meta charset="utf-8"><main>
<p role="status">Loading conversation until the tab renders.</p>
<template>'''+BODY.split('<main>', 1)[1].rsplit('</main>', 1)[0]+'''</template>
<script>
  function render() {
    if (document.hidden) return;
    document.querySelector('main').replaceChildren(document.querySelector('template').content);
  }
  document.addEventListener('visibilitychange', render);
  render();
</script></main>'''


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        data = (VISIBILITY_BODY if self.path == '/visibility' else BODY).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


with tempfile.TemporaryDirectory() as temp:
    profile = Path(temp)/'profile'
    port = reader.free_loopback_port()
    proc = subprocess.Popen([
        reader.chrome_executable(), '--user-data-dir='+str(profile),
        '--remote-debugging-address=127.0.0.1', '--remote-debugging-port='+str(port),
        '--no-first-run', '--no-default-browser-check', '--no-startup-window',
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        for _ in range(100):
            try:
                session = reader.debug_info('http://127.0.0.1:'+str(port))
                break
            except OSError:
                time.sleep(.1)
        else:
            raise RuntimeError('Temporary Chrome did not start')
        with sync_playwright() as pw:
            try:
                pw.chromium.connect_over_cdp(session['websocket'], timeout=15000)
            except Exception as error:
                assert 'Browser.setDownloadBehavior' in str(error), str(error)
                print('PASS: reproduced original download-behavior protocol error', flush=True)
            else:
                print('INFO: this Chrome supports the old download override', flush=True)
            browser = reader.connect_browser(pw, session)
            assert browser.contexts and not browser.contexts[0].pages

        reader.save_session(profile, dict(session, confirmed=True))
        target = f'http://127.0.0.1:{server.server_port}/conversation'
        # Only replace the production ChatGPT URL allowlist for this local fixture.
        with patch.object(reader, 'conversation_url', side_effect=lambda url: url):
            result = capture_browser.read_managed(
                target, profile, lambda *args: None, threading.Event(), 30,
                threading.Event(), True, True, scope='recent')
        assert result['message_count'] == 2 and result['partial']
        assert 'persistent context settings' in result['text']

        with sync_playwright() as pw:
            browser = reader.connect_browser(pw, session)
            foreground = browser.contexts[0].new_page()
            foreground.bring_to_front()
            hidden_target = f'http://127.0.0.1:{server.server_port}/visibility'
            baseline = capture_browser.create_task_page(browser, {}, True)
            baseline.goto(hidden_target)
            assert baseline.evaluate('document.hidden'), 'Fixture must start in a hidden tab'
            assert not reader.snapshot(baseline)['messages']
            baseline.close()
        with patch.object(reader, 'conversation_url', side_effect=lambda url: url):
            result = capture_browser.read_managed(
                hidden_target, profile, lambda *args: None, threading.Event(), 30,
                threading.Event(), True, False, scope='loaded')
        assert result['message_count'] == 2
        with sync_playwright() as pw:
            browser = reader.connect_browser(pw, session)
            foreground = next(page for page in browser.contexts[0].pages if page.url == 'about:blank')
            assert foreground.evaluate('!document.hidden'), 'Capture switched the selected tab'
            captured = next(page for page in browser.contexts[0].pages if page.url == hidden_target)
            assert captured.evaluate('document.hidden'), 'Focus emulation leaked after capture'
            captured.close()
            foreground.close()

        confirmed = threading.Event()
        def notify(state, message):
            if state == 'waiting_login':
                confirmed.set()
        result = web_reader.read(target, profile, notify, threading.Event(),
                                 login_complete=confirmed, background=True,
                                 close_new_tabs=True, language='en')
        assert 'persistent context settings' in result['text']
        with sync_playwright() as pw:
            browser = reader.connect_browser(pw, session, timeout=3000)
            assert not browser.contexts[0].pages, 'Only task-owned tabs should be closed'
        print('PASS: windowless Chrome connected; hidden conversation loaded without switching tabs; focus restored; webpage extracted; owned tabs cleaned up')
    finally:
        proc.terminate()
        proc.wait(timeout=15)
        server.shutdown()
        server.server_close()
