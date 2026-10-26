"""Exercise custom API UI and real worker HTTP against a synthetic local provider."""
import base64,io,json,os,sys,tempfile,threading,uuid,zipfile
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from PIL import Image
from playwright.sync_api import sync_playwright,expect
from secretary import ai,model_api
from secretary.server import Service,handler

key=uuid.uuid4().hex;requests=[]
class Provider(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append((self.path,payload,self.headers.get('Authorization')))
  if self.path.startswith('/redirect/'):
   self.send_response(302);self.send_header('Location','/leak/chat/completions');self.end_headers();return
  content=payload['messages'][1]['content'];prompt=content[0]['text'] if isinstance(content,list) else content
  if '仅输出 JSON' in prompt:
   answer=json.dumps({'title':'Synthetic API material','summary':'Synthetic API summary','tags':[],'answer':'Synthetic grouped API answer [1]','vision_text':'Synthetic visible blue diagram'})
  elif 'connection test' in prompt:answer='OK'
  else:answer='Synthetic API answer [1]'
  raw=json.dumps({'choices':[{'message':{'content':answer},'finish_reason':'stop'}]}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)

provider=ThreadingHTTPServer(('127.0.0.1',0),Provider);threading.Thread(target=provider.serve_forever,daemon=True).start();base_api=f'http://127.0.0.1:{provider.server_port}/v1'
with tempfile.TemporaryDirectory() as root:
 service=Service(root);service.archive.configure('codex',False);service.archive.add('Synthetic source','Synthetic searchable reference material')
 server=ThreadingHTTPServer(('127.0.0.1',0),handler(service));threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
 try:
  with sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path=os.environ.get('CHROME_PATH','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),headless=True)
   try:
    page=browser.new_page(viewport={'width':1280,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(base)
    try:expect(page.locator('#model-label')).to_have_text('ChatGPT · Codex',timeout=15000)
    except Exception:raise AssertionError('Startup diagnostics: '+repr(errors)+'; '+page.locator('#toast').inner_text()) from None
    page.locator('#settings-open').click();page.locator('#backend').select_option('api')
    expect(page.locator('#model-api-settings')).to_be_visible()
    page.locator('#api-base-url').fill(base_api);page.locator('#api-model').fill('synthetic-model');page.locator('#api-key').fill(key)
    page.locator('#api-test').click();expect(page.locator('#api-test-result')).to_have_text('API 连接测试成功',timeout=15000)
    assert len(requests)==1 and 'connection test' in requests[0][1]['messages'][1]['content']
    page.locator('#settings-save').click();expect(page.locator('#settings-dialog')).not_to_be_visible()
    expect(page.locator('#model-label')).to_contain_text('synthetic-model');expect(page.locator('#api-key')).to_have_value('')
    status=page.request.get(base+'/api/status').json();assert key not in json.dumps(status) and status['model_api']['has_key']
    assert key not in page.evaluate('JSON.stringify(localStorage)')
    page.locator('#message-input').fill('What is the synthetic reference?');page.locator('#send-button').click()
    expect(page.locator('#messages')).to_contain_text('Synthetic API answer',timeout=15000)
    stream=io.BytesIO();Image.new('RGB',(40,30),'blue').save(stream,format='PNG');png=stream.getvalue()
    page.locator('#message-input').fill('Explain this screenshot')
    page.locator('#file-input').set_input_files({'name':'synthetic.png','mimeType':'image/png','buffer':png});page.locator('#send-button').click()
    expect(page.locator('#messages')).to_contain_text('图片原件已保存但未识别',timeout=15000)
    assert isinstance(requests[-1][1]['messages'][1]['content'],str),'Disabled vision must not send images'
    page.locator('#settings-open').click();page.locator('#api-vision').check();page.locator('#settings-save').click()
    expect(page.locator('#settings-dialog')).not_to_be_visible()
    page.locator('#message-input').fill('Explain this second screenshot')
    page.locator('#file-input').set_input_files({'name':'synthetic.png','mimeType':'image/png','buffer':png});page.locator('#send-button').click()
    expect(page.locator('#messages .archive-card')).to_have_count(2,timeout=15000)
    try:expect(page.locator('.message.assistant').filter(has_text='Synthetic grouped API answer')).to_have_count(2,timeout=15000)
    except Exception:
     diagnostic={'requests_with_images':[isinstance(record[1]['messages'][1]['content'],list) for record in requests],'items':[{k:item[k] for k in ('title','state','error')} for item in service.archive.list()],'messages':page.locator('#messages').inner_text(),'page_errors':errors}
     raise AssertionError(json.dumps(diagnostic,ensure_ascii=False)) from None
    assert requests[-1][1]['messages'][1]['content'][1]['type']=='image_url'
    assert all(record[2]=='Bearer '+key for record in requests)
    with zipfile.ZipFile(io.BytesIO(service.backup())) as backup:assert all(key.encode() not in backup.read(name) for name in backup.namelist())
    page.locator('#settings-open').click();page.screenshot(path='/tmp/secretary-custom-model-api.png')
    expect(page.locator('#api-key')).to_have_value('');expect(page.locator('#api-key')).to_have_attribute('placeholder','密钥已保存，留空保持')
    page.reload();page.locator('#settings-open').click();expect(page.locator('#api-model')).to_have_value('synthetic-model')
    assert not errors,errors
    redirect={**model_api.read(root),'base_url':f'http://127.0.0.1:{provider.server_port}/redirect'}
    try:ai.run('Synthetic redirect test',redirect)
    except RuntimeError:pass
    else:raise AssertionError('Redirect must not forward the key')
    assert not any(path.startswith('/leak') for path,_,_ in requests)
    print('PASS: configurable API endpoint/model/key; real isolated worker and HTTP test; archive question; text-only image fallback; enabled base64 vision; saved key never returned or cached; backup excludes key; reload preserves config; redirects blocked; synthetic local service only')
   finally:browser.close()
 finally:service.close();server.shutdown();server.server_close();provider.shutdown();provider.server_close()
