"""Exercise desktop MCP setup and a PDF citation against a disposable library."""
import json
import os
import sys
import tempfile
import threading
import tomllib
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from secretary import bundles
from secretary.local_http import LocalHTTPServer
from secretary.memory_access import read_memory
from secretary.server import Service, handler
from test_large_pdf_preview import fixture

with tempfile.TemporaryDirectory() as temp:
    pdf = Path(temp)/'Review.pdf'
    fixture(pdf, pages=3)
    service = Service(Path(temp)/'library')
    try:
        raw, text = bundles.create('', [{'name':pdf.name, 'source':pdf}])
        try:
            service.archive.add(text=text, filename='materials.stellar.zip', data=raw)
        finally:
            bundles.cleanup(raw)
        with LocalHTTPServer(('127.0.0.1', 0), handler(service)) as server, sync_playwright() as playwright:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                browser = playwright.chromium.launch(executable_path=os.environ.get(
                    'CHROME_PATH', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'), headless=True)
                page = browser.new_page()
                page.goto(f'http://127.0.0.1:{server.server_port}/?panel=settings')
                expect(page.locator('#settings-dialog')).to_be_visible()
                page.locator('#memory-setup summary').click()
                page.locator('#memory-access').check()
                expect(page.locator('#memory-test')).to_be_enabled()
                for client in ('gemini','claude','codex'):
                    page.locator('#memory-client').select_option(client)
                    config = page.locator('#memory-config')
                    page.wait_for_function("(client)=>document.querySelector('#memory-config-path').textContent.includes(client)", arg={'gemini':'.gemini','claude':'.mcp','codex':'.codex'}[client])
                    data = tomllib.loads(config.input_value())['mcp_servers'] if client=='codex' else json.loads(config.input_value())['mcpServers']
                    assert Path(data['stellar-memory']['command']).exists()
                    assert data['stellar-memory']['args'][-1] == str(server.server_port)
                page.locator('#memory-test').click()
                expect(page.locator('#memory-result')).to_have_text('已通过本机记忆接口读取测试', timeout=35000)
                result = read_memory(service.archive, {'action':'search','query':'PAGETOKEN3'}, port=server.server_port)
                citation = result['items'][0]['citations'][0]
                assert citation['filename']==pdf.name and citation['page']==3
                page.goto(citation['url'])
                expect(page.locator('#pdf-reader')).to_be_visible()
                expect(page.locator('#pdf-reader h2')).to_have_text(pdf.name)
                expect(page.locator('#pdf-reader [data-pdf-start]')).to_have_value('3')
                expect(page.locator('#pdf-reader [data-pdf-image]')).to_be_visible()
                browser.close()
            finally:
                server.shutdown()
    finally:
        service.close()
    print('PASS: desktop opt-in, three client configurations, local read test and direct PDF citation')
