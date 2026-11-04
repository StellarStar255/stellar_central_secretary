"""Verify real detail-page gestures and HTTP validation using temporary paths."""
import os, sys, tempfile, threading, subprocess
from types import SimpleNamespace
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch, Mock
from playwright.sync_api import sync_playwright, expect
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from secretary.server import Service, handler
from secretary import local_paths

with tempfile.TemporaryDirectory() as root:
    service = Service(root)
    service.archive.configure('codex', False)
    folder = Path(root)/'中文 Project'
    folder.mkdir()
    file = folder/'example.command'
    file.write_text('must not execute')
    missing = folder/'missing'
    text = f'快速并发测试代码：\n{folder}\n文件：\n{file}\n不存在：\n{missing}\n网页：https://example.com/page\n<script>alert(1)</script>'
    item, _ = service.archive.add('Local folder example', text)
    service.archive.update(item, summary='Preserved summary', state='ready')
    before = service.archive.get(item)
    conversation, _ = service.archive.add('Conversation paths', f'用户：\n{folder}\n\n助手：\n位置是 `{folder}`', url='https://example.com/conversation')
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler(service))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        run = Mock()
        with patch.object(local_paths, 'subprocess', SimpleNamespace(run=run, SubprocessError=subprocess.SubprocessError)), patch('secretary.attachment_editor.launch') as launch, sync_playwright() as pw:
            executable = os.environ.get('CHROME_PATH') or ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' if sys.platform == 'darwin' else None)
            browser = pw.chromium.launch(headless=True, **({'executable_path': executable} if executable else {}))
            try:
                page = browser.new_page(viewport={'width': 1200, 'height': 1000})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}')
                page.locator(f'#recent-items [data-id="{item}"]').click()
                paths = page.locator('.archived-body .local-path')
                expect(paths).to_have_count(3)
                expect(page.locator('.archived-body')).to_have_text(text)
                paths.nth(0).click()
                assert run.call_count == 0 and launch.call_count == 0, 'A single click must not open anything'
                paths.nth(0).dblclick()
                expect(page.locator('#toast')).to_have_text('已打开本地文件夹')
                if sys.platform == 'darwin':
                    assert run.call_args.args[0] == ['/usr/bin/open', '-a', 'Finder', str(folder.resolve())]
                else:
                    assert launch.call_args.args == (folder,) and launch.call_args.kwargs == {'reveal': False}
                paths.nth(1).focus()
                page.keyboard.press('Enter')
                expect(page.locator('#toast')).to_have_text('已在文件夹中定位文件')
                assert launch.call_args.args == (file,) and launch.call_args.kwargs == {'reveal': True}
                opens = run.call_count + launch.call_count
                paths.nth(2).dblclick()
                expect(page.locator('#toast')).to_contain_text('本地路径不存在')
                assert run.call_count + launch.call_count == opens
                # A forged path must fail through the real authenticated HTTP route.
                rejected = page.evaluate('''async id => {
                    try { await api('/api/items/'+id+'/open-local-path',{path:'/tmp/unrecorded'}); return false }
                    catch(error) { return error.message }
                }''', item)
                assert '正文' in rejected and run.call_count + launch.call_count == opens
                after = service.archive.get(item)
                for key in ('text', 'summary', 'title', 'tags', 'state', 'updated'):
                    assert after[key] == before[key], key
                page.screenshot(path='/tmp/secretary-local-paths.png')
                page.reload()
                page.locator(f'#recent-items [data-id="{item}"]').click()
                expect(page.locator('.archived-body .local-path')).to_have_count(3)
                page.locator('#detail-dialog .dialog-head button').click()
                page.locator(f'#recent-items [data-id="{conversation}"]').click()
                expect(page.locator('.reader-message .local-path')).to_have_count(2)
                assert not errors, errors
                print('PASS: source preserved; existing paths survive reload; single click selects; double-click opens Finder; Enter reveals file without execution; missing and forged paths rejected; conversation paths render; no page errors')
            finally:
                browser.close()
    finally:
        service.close()
        server.shutdown()
        server.server_close()
