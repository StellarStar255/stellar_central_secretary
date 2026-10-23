"""Exercise the tutorial without writing to a user's archive or invoking a model."""
import os
import sys
import tempfile
import threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from secretary.server import Service,handler

with tempfile.TemporaryDirectory() as temp:
    service=Service(temp);service.archive.configure('codex',False)
    service.archive.add('保留的真实资料占位','本测试验证教程不会修改资料。')
    before=service.archive.export();settings=service.archive.settings()
    server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=os.environ.get('CHROME_PATH','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),headless=True)
            try:
                page=browser.new_page(viewport={'width':1280,'height':1000});errors=[];api_calls=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.on('request',lambda request:api_calls.append(request.url) if request.url.startswith(base+'/api/') else None)
                page.goto(base+'/tutorial');page.locator('#import-sample').click();assert page.locator('#next').is_enabled()
                page.locator('#next').click();page.locator('#practice-search').fill('6月 科学月刊');assert page.locator('#search-results .result').count()==1
                page.locator('#practice-search').fill('科学月刊 不存在');assert page.locator('#search-results .result').count()==0
                page.locator('#practice-search').fill('科学月刊　6月');assert page.locator('#search-results .result').count()==1
                page.screenshot(path='/tmp/secretary-tutorial-desktop.png',full_page=True)
                page.locator('#next').click();page.locator('#practice-title').click();page.locator('#practice-title-input').fill('未保存');page.locator('#practice-title-input').press('Escape')
                assert '科学月刊' in page.locator('#practice-title').inner_text()
                page.locator('#practice-title').click();page.locator('#practice-title-input').fill('我的六月阅读清单');page.locator('#practice-title-input').press('Enter')
                assert '我的六月阅读清单' in page.locator('#practice-title').inner_text()
                page.locator('#next').click()
                with page.expect_popup() as popup:page.locator('#practice-open-pdf').click()
                pdf=popup.value;pdf.wait_for_load_state();assert pdf.url.startswith('blob:');pdf.close()
                page.locator('#next').click();page.locator('#settings').click();page.locator('#practice-mode').click();assert page.locator('#mode-badge').inner_text()=='桌面练习'
                page.locator('#next').click();page.locator('#backup').click();assert 'files/' in page.locator('.tree').inner_text()
                assert page.locator('#completion').inner_text()=='已完成 6 / 6';page.locator('#next').click();assert '六个练习' in page.locator('#lesson-title').inner_text()
                page.locator('#reset').click();assert page.locator('#completion').inner_text()=='已完成 0 / 6'
                page.set_viewport_size({'width':390,'height':844});page.emulate_media(color_scheme='dark')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path='/tmp/secretary-tutorial-mobile.png',full_page=True)
                offline=browser.new_page();requests=[];offline.on('request',lambda r:requests.append(r.url) if r.url.startswith(('http:','https:')) else None)
                offline.goto((ROOT/'docs/tutorial.html').as_uri());offline.locator('#import-sample').click();offline.locator('#next').click();offline.locator('#practice-search').fill('6月 科学月刊');assert offline.locator('#search-results .result').count()==1
                assert not requests and not api_calls and not errors,(requests,api_calls,errors)
                assert service.archive.export()==before and service.archive.settings()==settings
                assert not (Path(temp)/'conversations.json').exists()
                print('PASS: all six tutorial exercises, search AND, rename/cancel, PDF popup, mode preview, backup, reset, mobile/dark layout, offline HTML; zero API requests and no archive/settings/model changes')
            finally:browser.close()
    finally:
        server.shutdown();server.server_close();service.close()
