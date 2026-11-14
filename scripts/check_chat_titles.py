"""Exercise durable chat names with a real browser and an isolated knowledge base."""
import copy,os,sys,tempfile,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary.server import Service,handler
from playwright.sync_api import sync_playwright,expect

class FixtureServer(ThreadingHTTPServer):request_queue_size=128
with tempfile.TemporaryDirectory() as temp:
 service=Service(temp);service.archive.configure('codex',False)
 item,_=service.archive.add('Sidebar test note','Keep this original text');service.archive.update(item,state='ready')
 chats=[{'id':'url','title':'https://chatgpt.com/c/example','updated':2,'messages':[{'id':'q','role':'user','text':'https://chatgpt.com/c/example'}]}, {'id':'other','title':'Other topic','updated':1,'messages':[{'id':'q2','role':'user','text':'Other topic'}]}]
 service.chat_history({'conversations':chats,'activeId':'url'})
 server=FixtureServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(executable_path=os.environ.get('CHROME_PATH') or ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' if sys.platform=='darwin' else None),headless=True)
   page=browser.new_page(viewport={'width':1280,'height':900});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(f'http://127.0.0.1:{server.server_port}')
   recent=page.locator('#recent-items [data-id="'+item+'"]');expect(recent).to_be_visible()
   dismiss=page.locator('[data-hide-recent="'+item+'"]');expect(dismiss).to_have_css('opacity','0')
   recent.hover();expect(dismiss).to_have_css('opacity','1');dismiss.click()
   expect(recent).to_have_count(0);expect(page.locator('#detail-dialog')).not_to_be_visible()
   assert service.archive.get(item)['text']=='Keep this original text'
   page.reload();expect(page.locator('[data-chat="url"]')).to_be_visible();expect(recent).to_have_count(0)
   assert service.archive.get(item)['state']=='ready'
   expect(page.locator('[data-chat="url"]')).to_have_text('ChatGPT 对话')
   page.locator('[data-rename-chat="other"]').click(force=True)
   page.locator('#chat-rename-input').fill('Cancelled');page.locator('#chat-rename-cancel').click()
   assert service.chat_history()['conversations'][1]['title']=='Other topic'
   page.locator('[data-rename-chat="other"]').click(force=True)
   page.locator('#chat-rename-input').fill('My <project>')
   page.evaluate('renderSidebar()')
   expect(page.locator('#chat-rename-input')).to_have_value('My <project>')
   page.locator('#chat-rename-save').click();expect(page.locator('#chat-rename-dialog')).not_to_be_visible()
   expect(page.locator('[data-chat="other"]')).to_have_text('My <project>')
   expect(page.locator('[data-chat="url"]')).to_have_class('conversation active')
   page.reload();expect(page.locator('[data-chat="other"]')).to_have_text('My <project>')
   page.locator('[data-chat="other"]').dblclick();expect(page.locator('#chat-rename-dialog')).to_be_visible()
   page.locator('#chat-rename-input').fill('Draft survives conflict')
   service.rename_chat('other','Changed elsewhere')
   page.locator('#chat-rename-save').click();expect(page.locator('#chat-rename-error')).not_to_be_empty()
   expect(page.locator('#chat-rename-input')).to_have_value('Draft survives conflict')
   page.keyboard.press('Escape');expect(page.locator('#chat-rename-dialog')).not_to_be_visible()
   page.reload();expect(page.locator('[data-chat="other"]')).to_have_text('Changed elsewhere')
   page.locator('[data-rename-chat="url"]').click(force=True);page.locator('#chat-rename-input').fill('Research notes');page.locator('#chat-rename-save').click()
   expect(page.locator('[data-chat="url"]')).to_have_text('Research notes');page.screenshot(path='/tmp/stellar-chat-titles.png')
   assert not errors,errors
   browser.close()
  print('PASS: recent item hover dismissal survives reload without deleting archive; friendly URL title, rename inactive chat, cancel, persistent save, escaping, double-click, conflict and draft preservation')
 finally:server.shutdown();server.server_close();service.close()
