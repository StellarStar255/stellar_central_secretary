"""Exercise library conversations through the real UI with deterministic model replies."""
import json,sys,tempfile,threading
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary.local_http import LocalHTTPServer
from secretary.server import Service,handler
from playwright.sync_api import sync_playwright,expect
calls=[]
def model(prompt,backend,**kwargs):
 payload=json.loads(prompt.split('\n',1)[1]);calls.append(payload)
 if 'passages' not in payload:return '{"queries":["Ollama RAM"]}'
 return 'Ollama 需要 16 GB 内存。[1]'
with tempfile.TemporaryDirectory() as root:
 service=Service(root);service.archive.configure('codex',False)
 item,_=service.archive.add('离线部署指南','Ollama RAM requirement: 16 GB. Runs on Apple Silicon.')
 server=LocalHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with patch('secretary.ai.run',side_effect=model),sync_playwright() as p:
   browser=p.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
   page=browser.new_page(viewport={'width':1280,'height':900});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(f'http://127.0.0.1:{server.server_port}');expect(page.locator('#model-label')).to_have_text('ChatGPT · Codex')
   page.locator('[data-suggestion="ask"]').click();expect(page.locator('#input-mode')).to_have_value('library')
   page.locator('#message-input').fill('介绍一下离线部署方案');page.locator('#send-button').click()
   expect(page.locator('.source')).to_have_count(1);expect(page.locator('.message.assistant .message-body')).to_have_text('Ollama 需要 16 GB 内存。[1]')
   evidence=page.locator('.answer-evidence').last
   evidence.locator('summary').click()
   expect(evidence).to_have_attribute('open','')
   expect(evidence.locator('blockquote')).to_contain_text('Ollama RAM requirement: 16 GB')
   page.reload();expect(page.locator('#input-mode')).to_have_value('library')
   expect(page.locator('.answer-evidence')).to_have_count(1)
   page.locator('#message-input').fill('它需要多少内存');page.locator('#send-button').click()
   expect(page.locator('.source')).to_have_count(2)
   page.locator('.answer-evidence').last.locator('summary').click()
   expect(page.locator('.answer-evidence').last).to_contain_text('参考的对话轮次 · 1')
   assert calls[-1]['history'][0]['question']=='介绍一下离线部署方案'
   assert calls[-1]['history'][0]['source_ids']==[item]
   assert len(service.archive.export())==1
   page.screenshot(path='/tmp/secretary-knowledge-chat.png')
   page.locator('.source').last.click();expect(page.locator('#detail-dialog')).to_be_visible();expect(page.locator('#detail-content')).to_contain_text('离线部署指南')
   page.locator('#detail-dialog .dialog-head button').click();page.locator('#new-chat').click()
   page.locator('#message-input').fill('继续');page.locator('#send-button').click();expect(page.locator('.source')).to_have_count(1)
   assert calls[-1]['history']==[]
   page.locator('#file-input').set_input_files({'name':'new.txt','mimeType':'text/plain','buffer':b'new material'})
   page.locator('#message-input').fill('附件呢');page.locator('#send-button').click()
   expect(page.locator('#toast')).to_have_text('请先归档附件，再在知识库对话中提问。')
   expect(page.locator('#message-input')).to_have_value('附件呢');assert len(service.archive.export())==1
   page.locator('#attachments [data-remove]').click()
   conversation_url='https://chatgpt.com/c/12345678-1234-1234-1234-123456789abc'
   model_calls=len(calls)
   with patch('secretary.server.fetch_page',return_value=('','')) as fetch,patch.object(service,'start_capture') as capture:
    expect(page.locator('#input-mode')).to_have_value('library')
    page.locator('#message-input').fill(conversation_url)
    page.locator('#send-button').click()
    expect(page.locator('.message.assistant .archive-card').last).to_be_visible()
    archived=[record for record in service.archive.export() if record['url']==conversation_url]
    assert len(archived)==1 and archived[0]['kind']=='link'
    fetch.assert_called_once_with(conversation_url)
    capture.assert_called_once_with(archived[0]['id'])
    assert len(calls)==model_calls
    expect(page.locator('#input-mode')).to_have_value('library')
   page.locator('#archive-only').check()
   second_url='https://example.com/reference'
   page.locator('#message-input').fill(conversation_url+'\n'+second_url)
   page.locator('#send-button').click()
   expect(page.locator('.message.assistant .archive-card')).to_have_count(2)
   group=next(record for record in service.archive.export() if record['filename']=='materials.stellar.zip')
   assert [link['url'] for link in service.archive.get(group['id'])['group_links']]==[conversation_url,second_url]
   assert len(calls)==model_calls
   page.locator('#settings-open').click();page.locator('#ui-language').select_option('en')
   expect(page.locator('#input-mode option[value="library"]')).to_have_text('Library chat')
   assert not errors,errors
   browser.close()
   print('PASS: real browser + HTTP server, library question and follow-up, source evidence, attachment preservation, URL-only archive and capture routing, and English UI')
 finally:server.shutdown();server.server_close();service.close()
