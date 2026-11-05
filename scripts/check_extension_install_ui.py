"""Installer-compatible extension setup using isolated files and no browser changes."""
import io,json,os,sys,tempfile,threading,zipfile
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary.server import Service,handler
from secretary import extension_install
from playwright.sync_api import sync_playwright,expect

with tempfile.TemporaryDirectory() as root:
    service=Service(root);service.archive.configure('codex',False)
    server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
    def open_folder(data):return extension_install.prepare(data)
    try:
        with patch('secretary.extension_install.open_folder',side_effect=open_folder) as opened,patch('secretary.ai.run') as model,sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,executable_path=os.environ.get('CHROME_PATH') or ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' if sys.platform=='darwin' else None))
            try:
                page=browser.new_page(viewport={'width':1280,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.add_init_script("Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.copiedExtensionPath=text}}})")
                page.goto(base);expect(page.locator('#model-label')).to_have_text('ChatGPT · Codex',timeout=15000)
                page.locator('#settings-open').click();page.locator('#settings-dialog [data-extension-help]').click()
                expect(page.locator('#extension-copy-path')).to_be_enabled();path=page.locator('#extension-directory').input_value();assert path==str((Path(root)/'browser-extension').resolve())
                assert (Path(path)/'manifest.json').is_file();expect(page.locator('#extension-dialog')).not_to_contain_text('项目目录')
                page.locator('#extension-copy-path').click();expect(page.locator('#toast')).to_have_text('扩展文件夹路径已复制');assert page.evaluate('window.copiedExtensionPath')==path
                page.locator('#extension-open-folder').click();expect(page.locator('#toast')).to_have_text('扩展文件夹已打开');assert opened.call_count==1
                response=page.request.get(base+'/api/browser-extension/download');assert response.ok
                with zipfile.ZipFile(io.BytesIO(response.body())) as z:assert json.loads(z.read('Stellar-Capture-Extension/manifest.json'))['manifest_version']==3
                assert page.request.post(base+'/api/browser-extension/prepare',data={}).status==403
                page.screenshot(path='/tmp/secretary-extension-installer-guide.png')
                page.locator('#extension-dialog .dialog-head button').click();page.locator('#ui-language').select_option('en');expect(page.locator('html')).to_have_attribute('lang','en');expect(page.locator('#ui-language')).to_be_enabled()
                page.route('**/api/browser-extension/prepare',lambda route:route.fulfill(status=500,content_type='application/json',body=json.dumps({'error':'Synthetic prepare failure'})))
                page.locator('#settings-dialog [data-extension-help]').click();expect(page.locator('#extension-retry')).to_be_visible();expect(page.locator('#extension-open-folder')).to_be_disabled();expect(page.locator('#extension-prepare-status')).to_have_text('Synthetic prepare failure')
                page.unroute('**/api/browser-extension/prepare');page.locator('#extension-retry').click();expect(page.locator('#extension-copy-path')).to_be_enabled();expect(page.locator('#extension-dialog')).to_contain_text('Extension installation folder');expect(page.locator('#extension-directory')).to_have_value(path)
                assert not model.called and not errors,errors
                print('PASS: setup from settings, stable installer folder with manifest, clipboard path, explicit folder open, ZIP download, POST-token check, failure/retry, English/Chinese guide, no model or browser setting changes')
            finally:browser.close()
    finally:server.shutdown();server.server_close();service.close()
