"""Exercise the tutorial without writing to a user's archive or invoking a model."""
import os
import sys
import tempfile
import threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from playwright.sync_api import expect, sync_playwright

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from secretary.server import Service,handler


def check_first_run(browser, directory):
    root=Path(directory)/'fresh'
    service=Service(root,first_run_tutorial=True)
    service.archive.set_language('en')
    server=ThreadingHTTPServer(('127.0.0.1',0),handler(service))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    base=f'http://127.0.0.1:{server.server_port}'
    context=browser.new_context()
    try:
        page=context.new_page()
        page.goto(base)
        popup=page.locator('#first-run-tutorial')
        expect(popup).to_be_visible()
        expect(page.locator('#tutorial-update-notice')).to_be_hidden()
        iframe=page.frame_locator('#first-run-tutorial-frame')
        expect(iframe.locator('h1')).to_have_text('Learn by trying it yourself.')
        memory_guide=iframe.locator('#tutorial-memory-mcp')
        summary=memory_guide.locator('summary')
        setup_link=memory_guide.get_by_role('link')
        expect(summary).to_have_text('Connect your library to other AI tools (MCP)')
        expect(memory_guide.locator('ol')).to_be_hidden()
        summary.press('Enter')
        expect(memory_guide.locator('ol')).to_be_visible()
        expect(memory_guide.locator('ol')).to_contain_text('Connect AI assistants')
        expect(setup_link).to_have_attribute('href', 'https://github.com/StellarStar255/stellar_central_secretary/blob/main/README.md#memory-mcp')
        language=iframe.locator('#tutorial-language')
        language.select_option('zh')
        expect(summary).to_have_text('把知识库接到其他 AI（MCP）')
        expect(setup_link).to_have_attribute('href', 'https://github.com/StellarStar255/stellar_central_secretary/blob/main/README.zh-CN.md#记忆-mcp-接口')
        language.select_option('en')
        context.route('https://github.com/**/README.md', lambda route: route.fulfill(
            content_type='text/html', body='<title>Memory MCP</title>'))
        with page.expect_popup() as docs:
            setup_link.click()
        expect(docs.value).to_have_url('https://github.com/StellarStar255/stellar_central_secretary/blob/main/README.md#memory-mcp')
        docs.value.close()
        summary.click()
        iframe.locator('#import-sample').click()
        iframe.locator('#next').click()
        iframe.locator('#practice-search').fill('June Science Monthly')
        expect(iframe.locator('#search-results .result')).to_have_count(1)
        iframe.locator('#next').click()
        iframe.locator('#practice-title').click()
        iframe.locator('#practice-title-input').fill('My reading list')
        iframe.locator('#practice-title-input').press('Enter')
        iframe.locator('#next').click()
        iframe.locator('#practice-open-pdf').click()
        expect(iframe.locator('#sample-pdf-preview')).to_contain_text('Tutorial PDF')
        iframe.locator('#next').click()
        iframe.locator('#settings').click()
        iframe.locator('#practice-mode').click()
        iframe.locator('#next').click()
        iframe.locator('#backup').click()
        iframe.locator('#next').click()
        expect(iframe.locator('#completion')).to_have_text('Completed 6 / 6')
        iframe.locator('#return-app').click()
        expect(popup).to_be_hidden()
        page.reload()
        expect(page.locator('#model-label')).to_have_text('ChatGPT · Codex')
        expect(popup).to_be_hidden()
        page.locator('#settings-open').click()
        with page.expect_popup() as manual:
            page.locator('#tutorial-open').click()
        expect(manual.value.locator('h1')).to_have_text('Learn by trying it yourself.')
        assert not service.archive.list()
    finally:
        context.close()
        server.shutdown();server.server_close();service.close()
    restarted=Service(root,first_run_tutorial=True)
    try:
        assert not restarted.tutorial_pending
    finally:
        restarted.close()


def check_skipped_or_upgraded(browser, directory):
    for scenario in ('skipped','upgrade','dismissed'):
        legacy=scenario!='skipped'
        root=Path(directory)/scenario
        if legacy:
            old=Service(root)
            old.close()
        service=Service(root,first_run_tutorial=True)
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(service))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        page=browser.new_page()
        try:
            page.goto(f'http://127.0.0.1:{server.server_port}')
            popup=page.locator('#first-run-tutorial')
            if not legacy:
                expect(popup).to_be_visible()
                popup.get_by_role('button',name='跳过教程').click()
                expect(popup).to_be_hidden()
                page.reload()
            expect(page.locator('#model-label')).to_have_text('ChatGPT · Codex')
            expect(popup).to_be_hidden()
            assert not service.tutorial_pending
            notice=page.locator('#tutorial-update-notice')
            if scenario=='dismissed':
                expect(notice).to_be_visible()
                notice.get_by_role('button',name='关闭新功能提示').click()
                expect(notice).to_be_hidden()
            elif legacy:
                expect(notice).to_be_visible()
                open_guide=notice.get_by_role('link')
                expect(open_guide).to_have_attribute('href','/tutorial?lang=zh#whats-new')
                with page.expect_popup() as opened:
                    open_guide.click()
                guide=opened.value
                expect(guide.locator('#whats-new-title')).to_have_text('本版新功能')
                guide.get_by_text('Windows 启动时找不到记忆目录',exact=True).click()
                guide.locator('[data-recovery="existing"]').click()
                expect(guide.locator('#recovery-practice-feedback')).to_contain_text('archive.sqlite3')
                guide.locator('#tutorial-language').select_option('en')
                expect(guide.locator('#recovery-practice-feedback')).to_contain_text('If you moved your library')
                guide.locator('[data-recovery="new"]').click()
                expect(guide.locator('#recovery-practice-feedback')).to_contain_text('Future launches open it automatically')
                expect(guide.locator('#recovery-practice button')).to_have_count(3)
                guide.close()
                expect(notice).to_be_hidden()
                page.reload()
                expect(page.locator('#model-label')).to_have_text('ChatGPT · Codex')
                expect(notice).to_be_hidden()
                page.locator('#settings-open').click()
                expect(page.locator('#tutorial-whats-new')).to_be_visible()
                with page.expect_popup() as reopened:
                    page.locator('#tutorial-whats-new').click()
                expect(reopened.value.locator('#whats-new-title')).to_be_visible()
                reopened.value.close()
            else:
                expect(notice).to_be_hidden()
        finally:
            page.close()
            server.shutdown();server.server_close();service.close()
        if legacy:
            restarted=Service(root,first_run_tutorial=True)
            try:
                assert restarted.tutorial_update is None
            finally:
                restarted.close()

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
                offline.set_viewport_size({'width':390,'height':844})
                offline.locator('#tutorial-memory-mcp summary').click()
                expect(offline.locator('#tutorial-memory-mcp ol')).to_contain_text('连接 AI 助手')
                assert offline.evaluate('document.documentElement.scrollWidth<=innerWidth')
                assert not requests and not api_calls and not errors,(requests,api_calls,errors)
                assert service.archive.export()==before and service.archive.settings()==settings
                assert not (Path(temp)/'conversations.json').exists()
                print('PASS: all six tutorial exercises, search AND, rename/cancel, PDF popup, mode preview, backup, reset, mobile/dark layout, offline HTML; zero API requests and no archive/settings/model changes')
                check_first_run(browser,temp)
                check_skipped_or_upgraded(browser,temp)
                print('PASS: packaged first run opens the embedded tutorial once; finish, skip, reload, restart, upgrade and manual reopen')
            finally:browser.close()
    finally:
        server.shutdown();server.server_close();service.close()
